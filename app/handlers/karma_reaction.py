"""Handler for karma changes via message reactions."""
import asyncio

from aiogram import Bot, Router, types
from aiogram.enums import ChatMemberStatus
from aiogram.types import LinkPreviewOptions, ReactionTypeEmoji
from aiogram.utils.text_decorations import html_decoration as hd

from app.config.karmic_triggers import MINUS_EMOJI, PLUS_EMOJI
from app.infrastructure.database.models import Chat, ChatSettings, User
from app.infrastructure.database.repo.user import UserRepo
from app.models.config import Config
from app.services.change_karma import change_karma
from app.services.karma_percentile import is_user_in_top_percentile
from app.services.remove_message import delete_message, remove_kb
from app.utils.exceptions import CantChangeKarma, DontOffendRestricted, SubZeroKarma
from app.utils.log import Logger

from . import keyboards as kb

logger = Logger(__name__)
router = Router(name=__name__)

# Reaction coefficient for karma change
REACTION_COEFFICIENT = 0.1


def get_how_change_text(number: float) -> str:
    if number > 0:
        return "увеличили"
    if number < 0:
        return "уменьшили"
    else:
        raise ValueError("karma_change must be float and not 0")


def get_karma_change_from_reaction(emoji: str) -> float | None:
    """
    Determine karma change value from reaction emoji.

    Returns:
        Positive value for positive reactions, negative for negative, None if unknown
    """
    if emoji in PLUS_EMOJI:
        return REACTION_COEFFICIENT
    if emoji in MINUS_EMOJI:
        return -REACTION_COEFFICIENT
    return None


async def is_user_chat_member(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Check if user is a member of the chat."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in (
            ChatMemberStatus.CREATOR,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.RESTRICTED,
        )
    except Exception as e:
        logger.warning(
            "Failed to check chat membership for user {user_id} in chat {chat_id}: {error}",
            user_id=user_id,
            chat_id=chat_id,
            error=e,
        )
        return False


@router.message_reaction()
async def on_reaction_change(
    reaction: types.MessageReactionUpdated,
    bot: Bot,
    config: Config,
    user_repo: UserRepo,
):
    """Handle message reaction updates."""
    # Only process reactions in groups/supergroups
    if reaction.chat.type not in ("group", "supergroup"):
        return

    # Get or create user who reacted
    reactor_user = await user_repo.get_or_create_user(reaction.user)

    # Get or create chat
    chat, _ = await Chat.get_or_create(chat_id=reaction.chat.id)

    # Get chat settings
    chat_settings = await ChatSettings.get_or_none(chat=chat)
    if chat_settings is None or not chat_settings.karma_counting:
        return

    # Check if reactor is in top 30% by karma
    if not await is_user_in_top_percentile(reactor_user, chat, percentile=0.3):
        logger.info(
            "User {user} not in top 30%% in chat {chat}, reaction ignored",
            user=reactor_user.tg_id,
            chat=chat.chat_id,
        )
        return

    # Check if reactor is a chat member
    if not await is_user_chat_member(bot, reaction.chat.id, reaction.user.id):
        logger.info(
            "User {user} is not a member of chat {chat}, reaction ignored",
            user=reactor_user.tg_id,
            chat=chat.chat_id,
        )
        return

    # Determine karma changes from added/removed reactions
    karma_changes = []

    # Process new reactions (added)
    for new_reaction in reaction.new_reaction:
        if isinstance(new_reaction, ReactionTypeEmoji):
            karma_change = get_karma_change_from_reaction(new_reaction.emoji)
            if karma_change is not None:
                karma_changes.append(karma_change)

    # Process removed reactions (subtract the reverse)
    for old_reaction in reaction.old_reaction:
        if isinstance(old_reaction, ReactionTypeEmoji):
            karma_change = get_karma_change_from_reaction(old_reaction.emoji)
            if karma_change is not None:
                # Reverse the previous change
                karma_changes.append(-karma_change)

    # If no valid karma changes, return
    if not karma_changes:
        return

    # Sum all karma changes
    total_karma_change = sum(karma_changes)
    if abs(total_karma_change) < 0.001:  # Ignore near-zero changes
        return

    # Get message to determine its author (target user)
    # NOTE: Telegram Bot API doesn't provide message author info in MessageReactionUpdated
    # We try to forward the message to extract the original sender from forward_origin
    # This requires the bot to have permission to forward messages
    # TODO: Consider implementing a middleware to store message authors in DB for better reliability
    try:
        forwarded = await bot.forward_message(
            chat_id=reaction.user.id,
            from_chat_id=reaction.chat.id,
            message_id=reaction.message_id,
        )

        # Extract original sender from forward origin
        target_tg_user = None
        if forwarded.forward_origin:
            if hasattr(forwarded.forward_origin, 'sender_user') and forwarded.forward_origin.sender_user:
                target_tg_user = forwarded.forward_origin.sender_user
            else:
                # User has hidden their account or it's a channel message
                logger.debug(
                    "Can't determine message owner from forward origin in chat {chat} (hidden account or channel)",
                    chat=chat.chat_id,
                )
                return
        # If message wasn't forwarded, it might be from a bot or the original message in the chat
        # We can use the `from` field from the forwarded message
        elif forwarded.from_user and not forwarded.from_user.is_bot:
            target_tg_user = forwarded.from_user

        if target_tg_user is None:
            logger.debug(
                "Can't determine message author for reaction in chat {chat}",
                chat=chat.chat_id,
            )
            return

    except Exception as e:
        logger.warning(
            "Failed to forward message to get author info: {error}",
            error=e,
        )
        return

    # Get or create target user
    target_user = await user_repo.get_or_create_user(target_tg_user)

    # Change karma
    try:
        result_change_karma = await change_karma(
            user=reactor_user,
            target_user=target_user,
            chat=chat,
            how_change=total_karma_change,
            is_restriction_enabled=chat_settings.karmic_restrictions,
            bot=bot,
            user_repo=user_repo,
            comment="(реакция)",
        )
    except SubZeroKarma:
        return  # Silent fail for reactions
    except DontOffendRestricted:
        return  # Silent fail for reactions
    except CantChangeKarma as e:
        logger.info(
            "User {user} can't change karma via reaction, {e}",
            user=reactor_user.tg_id,
            e=e,
        )
        return

    # Prepare notification text
    if result_change_karma.was_auto_restricted:
        notify_text = config.auto_restriction.render_auto_restriction(
            target_user, result_change_karma.count_auto_restrict
        )
    elif result_change_karma.karma_after < 0 and chat_settings.karmic_restrictions:
        notify_text = config.auto_restriction.render_negative_karma_notification(
            target_user, result_change_karma.count_auto_restrict
        )
    else:
        notify_text = ""

    # Calculate how much karma was actually changed
    how_changed_karma = (
        result_change_karma.user_karma.karma
        - result_change_karma.karma_after
        + result_change_karma.abs_change
    )

    # Send notification message
    try:
        msg = await bot.send_message(
            chat_id=reaction.chat.id,
            text="<b>{actor_name}</b>, Вы {how_change} карму <b>{target_name}</b> "
            "до <b>{karma_new:.2f}</b> ({power:+.2f}) (реакция)\n\n{notify_text}".format(
                actor_name=hd.quote(reactor_user.fullname),
                how_change=get_how_change_text(total_karma_change),
                target_name=hd.quote(target_user.fullname),
                karma_new=result_change_karma.karma_after,
                power=result_change_karma.abs_change,
                notify_text=notify_text,
            ),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            reply_markup=kb.get_kb_karma_cancel(
                user=reactor_user,
                karma_event=result_change_karma.karma_event,
                rollback_karma=-how_changed_karma,
                moderator_event=result_change_karma.moderator_event,
            ),
        )

        # Schedule message deletion
        asyncio.create_task(delete_message(msg, config.time_to_cancel_actions))

    except Exception as e:
        logger.error(
            "Failed to send karma change notification: {error}",
            error=e,
        )

"""Handler for karma changes via message reactions."""
import asyncio

from aiogram import Bot, F, Router, types
from aiogram.enums import ChatMemberStatus
from aiogram.types import LinkPreviewOptions
from aiogram.utils.text_decorations import html_decoration as hd

from app.filters.karma_reaction import KarmaReactionFilter
from app.infrastructure.database.models import Chat, ChatSettings, User
from app.infrastructure.database.repo.user import UserRepo
from app.models.config import Config
from app.services.adaptive_trottle import AdaptiveThrottle
from app.services.change_karma import change_karma
from app.services.karma_percentile import get_user_percentile
from app.services.remove_message import delete_message, remove_kb
from app.utils.exceptions import CantChangeKarma, DontOffendRestricted, SubZeroKarma
from app.utils.log import Logger

from . import keyboards as kb

logger = Logger(__name__)
router = Router(name=__name__)
a_throttle = AdaptiveThrottle()


def get_how_change_text(number: float) -> str:
    if number > 0:
        return "увеличили"
    if number < 0:
        return "уменьшили"
    else:
        raise ValueError("karma_change must be float and not 0")


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


async def too_fast_change_karma_reaction(
    reaction: types.MessageReactionUpdated,
    user: User | None = None,
    *_,
    **__
):
    """Called when user changes karma via reactions too frequently."""
    # Note: We can't reply to reactions, so we just log and ignore
    user_id = user.tg_id if user else reaction.user.id
    logger.info(
        "User {user} is changing karma via reactions too frequently",
        user=user_id,
    )


@router.message_reaction(
    F.chat.type.in_(["group", "supergroup"]),
    KarmaReactionFilter(),
)
@a_throttle.throttled(rate=30, on_throttled=too_fast_change_karma_reaction)
async def on_reaction_change(
    reaction: types.MessageReactionUpdated,
    karma: dict,
    user: User,
    chat: Chat,
    chat_settings: ChatSettings,
    config: Config,
    bot: Bot,
    user_repo: UserRepo,
):
    """Handle message reaction updates."""
    # Get data from filter
    total_karma_change = karma["karma_change"]

    # Check if reactor is in top 30% by karma
    required_percentile = 0.3
    reactor_percentile = await get_user_percentile(user, chat)

    if reactor_percentile is None or reactor_percentile >= required_percentile:
        # User either has no karma or is not in top 30%
        if reactor_percentile is not None:
            # Show informational message for 10 seconds
            try:
                msg = await bot.send_message(
                    chat_id=reaction.chat.id,
                    text=(
                        f"<b>{hd.quote(user.fullname)}</b>, для изменения кармы с помощью реакций "
                        f"ваша карма должна быть в пределах Tоп-{required_percentile * 100:.0f}%, "
                        f"в то время как ваша фактическая карма входит в Топ-{reactor_percentile * 100:.0f}%."
                    ),
                )
                asyncio.create_task(delete_message(msg, 10))
            except Exception as e:
                logger.warning(
                    "Failed to send percentile notification: {error}",
                    error=e,
                )

        logger.info(
            "User {user} not in top {percentile}%% in chat {chat} (actual: {actual}%%), reaction ignored",
            user=user.tg_id,
            percentile=required_percentile * 100,
            actual=reactor_percentile * 100 if reactor_percentile is not None else "N/A",
            chat=chat.chat_id,
        )
        return

    # Check if reactor is a chat member
    if not await is_user_chat_member(bot, reaction.chat.id, user.tg_id):
        logger.info(
            "User {user} is not a member of chat {chat}, reaction ignored",
            user=user.tg_id,
            chat=chat.chat_id,
        )
        return

    # Get message to determine its author (target user)
    # NOTE: Telegram Bot API doesn't provide message author info in MessageReactionUpdated
    # We try to forward the message to extract the original sender from forward_origin
    # This requires the bot to have permission to forward messages
    # TODO: Consider implementing a middleware to store message authors in DB for better reliability
    try:
        forwarded = await bot.forward_message(
            chat_id=user.tg_id,
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
            user=user,
            target_user=target_user,
            chat=chat,
            how_change=total_karma_change,
            is_restriction_enabled=chat_settings.karmic_restrictions,
            bot=bot,
            user_repo=user_repo,
            comment=karma["comment"],
        )
    except SubZeroKarma:
        return  # Silent fail for reactions
    except DontOffendRestricted:
        return  # Silent fail for reactions
    except CantChangeKarma as e:
        logger.info(
            "User {user} can't change karma via reaction, {e}",
            user=user.tg_id,
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
                actor_name=hd.quote(user.fullname),
                how_change=get_how_change_text(total_karma_change),
                target_name=hd.quote(target_user.fullname),
                karma_new=result_change_karma.karma_after,
                power=result_change_karma.abs_change,
                notify_text=notify_text,
            ),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            reply_markup=kb.get_kb_karma_cancel(
                user=user,
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

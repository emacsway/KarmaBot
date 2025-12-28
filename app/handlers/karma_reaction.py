"""Handler for karma changes via message reactions."""
import asyncio
from datetime import timedelta

from aiogram import Bot, F, Router, types
from aiogram.types import LinkPreviewOptions
from aiogram.utils.text_decorations import html_decoration as hd

from app.filters.karma_reaction import KarmaReactionFilter
from app.filters.reaction_has_target import ReactionHasTargetFilter
from app.filters.user_is_chat_member import UserIsChatMember
from app.filters.user_not_restricted import UserNotRestricted
from app.filters.user_percentile import UserPercentileFilter
from app.handlers.decorators.throttle import (
    RateLimit,
    Throttle,
    ThrottlePerTarget,
)
from app.infrastructure.database.models import Chat, ChatSettings, User
from app.infrastructure.database.repo.user import UserRepo
from app.models.config import Config
from app.services.change_karma import change_karma
from app.services.remove_message import delete_message, remove_kb
from app.utils.exceptions import CantChangeKarma, DontOffendRestricted, SubZeroKarma
from app.utils.log import Logger

from . import keyboards as kb

logger = Logger(__name__)
router = Router(name=__name__)
throttle = Throttle()
throttle_per_target = ThrottlePerTarget()


def get_how_change_text(number: float) -> str:
    if number > 0:
        return "увеличили"
    if number < 0:
        return "уменьшили"
    else:
        raise ValueError("karma_change must be float and not 0")


async def too_fast_change_karma_reaction(
    reaction: types.MessageReactionUpdated,
    user: User | None = None,
    chat: Chat | None = None,
    bot: Bot | None = None,
    target: User | None = None,
    *_,
    **__
):
    """Called when user changes karma via reactions too frequently."""
    # Send notification message
    if target is not None:
        text = f"<b>{hd.quote(user.fullname)}</b>, Вы слишком часто меняете карму пользователю {hd.quote(target.fullname)}."
    else:
        text = f"<b>{hd.quote(user.fullname)}</b>, Вы слишком часто меняете карму."
    if bot and chat and user:
        try:
            msg = await bot.send_message(
                chat_id=chat.chat_id,
                text=text,
                disable_notification=False
            )
            asyncio.create_task(delete_message(msg, 10))
        except Exception as e:
            logger.warning(
                "Failed to send throttle notification: {error}",
                error=e,
            )


@router.message_reaction(
    F.chat.type.in_(["group", "supergroup"]),
    ReactionHasTargetFilter(),
    KarmaReactionFilter(),
    UserPercentileFilter(required_percentile=0.5),
    UserIsChatMember(),
    UserNotRestricted(),
)
@throttle_per_target.throttled(
    RateLimit(rate=3, duration=timedelta(hours=1)),
    RateLimit(rate=5, duration=timedelta(days=1)),
    on_throttled=too_fast_change_karma_reaction,
)
@throttle.throttled(
    RateLimit(rate=10, duration=timedelta(hours=1)),
    RateLimit(rate=20, duration=timedelta(days=1)),
    on_throttled=too_fast_change_karma_reaction,
)
async def on_reaction_change(
    reaction: types.MessageReactionUpdated,
    karma: dict,
    user: User,
    chat: Chat,
    chat_settings: ChatSettings,
    target: User,
    config: Config,
    bot: Bot,
    user_repo: UserRepo,
):
    """Handle message reaction updates."""
    # Get data from filter
    total_karma_change = karma["karma_change"]

    # Change karma
    try:
        result_change_karma = await change_karma(
            user=user,
            target_user=target,
            chat=chat,
            how_change=total_karma_change,
            is_restriction_enabled=chat_settings.karmic_restrictions,
            bot=bot,
            user_repo=user_repo,
            comment=karma["comment"],
            date=reaction.date
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
            target, result_change_karma.count_auto_restrict
        )
    elif result_change_karma.karma_after < 0 and chat_settings.karmic_restrictions:
        notify_text = config.auto_restriction.render_negative_karma_notification(
            target, result_change_karma.count_auto_restrict
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
            chat_id=chat.chat_id,
            text="<b>{actor_name}</b>, Вы {how_change} карму <b>{target_name}</b> "
            "до <b>{karma_new:.2f}</b> ({power:+.2f}) (реакция)\n\n{notify_text}".format(
                actor_name=hd.quote(user.fullname),
                how_change=get_how_change_text(total_karma_change),
                target_name=hd.quote(target.fullname),
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
            reply_to_message_id=reaction.message_id,
            disable_notification=True,
        )

        # Schedule message deletion
        asyncio.create_task(delete_message(msg, config.time_to_cancel_actions))

    except Exception as e:
        logger.error(
            "Failed to send karma change notification: {error}",
            error=e,
        )

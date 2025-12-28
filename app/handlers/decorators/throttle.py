"""Throttle decorator for limiting karma changes per target user."""
import functools
import typing
from datetime import timedelta

from aiogram import Bot
from aiogram.types import TelegramObject
from tortoise.expressions import RawSQL

from app.infrastructure.database.models import Chat, KarmaEvent, User, UserKarma
from app.utils.log import Logger

logger = Logger(__name__)


class RateLimit(typing.NamedTuple):
    """Rate limit configuration."""
    rate: int  # Number of allowed requests
    duration: timedelta  # Time period


class Throttle:
    """
    Throttle decorator that limits karma changes.

    Checks that total absolute karma given within duration
    doesn't exceed rate * user's karma power.
    """

    def throttled(
        self,
        *rate_limits: RateLimit,
        on_throttled: typing.Optional[typing.Callable] = None,
    ):
        """
        Throttle decorator for limiting karma changes.

        Args:
            *rate_limits: Variable number of RateLimit tuples (rate, duration)
            on_throttled: Callback called when throttled

        Example:
            @throttle.throttled(
                RateLimit(rate=3, duration=timedelta(hours=1)),
                RateLimit(rate=5, duration=timedelta(days=1)),
                on_throttled=my_callback,
            )
            async def karma_change(...):
                ...
        """
        if not rate_limits:
            raise ValueError("At least one rate limit must be provided")

        def decorator(func):
            @functools.wraps(func)
            async def wrapped(event: TelegramObject, *args, **kwargs):
                # Extract required parameters
                user: User = kwargs["user"]
                chat: Chat = kwargs["chat"]
                bot: Bot = kwargs["bot"]

                # Get user's karma power
                user_power = await UserKarma.get_power(user=user, chat=chat)
                now = event.date

                # Check each rate limit
                for rate_limit in rate_limits:
                    # Calculate time window
                    start_time = now - rate_limit.duration

                    # Sum absolute karma changes in this window using DB aggregation
                    result = await (
                        KarmaEvent.filter(
                            user_from=user,
                            chat=chat,
                            date__gte=start_time,
                        )
                        # TODO: use field how_change instead without power?
                        .annotate(total=RawSQL("COALESCE(SUM(ABS(how_match_change)), 0)"))
                        .values_list("total", flat=True)
                    )

                    total_karma_given = result[0] if result else 0

                    # Check if exceeded limit
                    max_allowed = rate_limit.rate * user_power

                    logger.debug(
                        "Throttle check: user={user}, chat={chat}, "
                        "total_karma={total}, max_allowed={max}, rate={rate}, power={power}",
                        user=user.tg_id,
                        chat=chat.chat_id,
                        total=total_karma_given,
                        max=max_allowed,
                        rate=rate_limit.rate,
                        power=user_power,
                    )

                    if total_karma_given >= max_allowed:
                        logger.info(
                            "User {user} exceeded karma rate limit in chat {chat}: "
                            "{total} >= {max} (rate={rate}, power={power})",
                            user=user.tg_id,
                            chat=chat.chat_id,
                            total=total_karma_given,
                            max=max_allowed,
                            rate=rate_limit.rate,
                            power=user_power,
                        )

                        # Call on_throttled callback if provided
                        if on_throttled is not None:
                            await on_throttled(
                                event,
                                user=user,
                                chat=chat,
                                bot=bot,
                            )

                        # Don't call the original function
                        return None

                # All limits not exceeded, proceed
                logger.debug(
                    "Rate limit OK for user {user} in chat {chat}",
                    user=user.tg_id,
                    chat=chat.chat_id,
                )
                return await func(event, *args, **kwargs)

            return wrapped

        return decorator


class ThrottlePerTarget:
    """
    Throttle decorator that limits karma changes per target user.

    Checks that total absolute karma given to target user within duration
    doesn't exceed rate * user's karma power.
    """

    def throttled(
        self,
        *rate_limits: RateLimit,
        on_throttled: typing.Optional[typing.Callable] = None,
    ):
        """
        Throttle decorator for limiting karma changes per target.

        Args:
            *rate_limits: Variable number of RateLimit tuples (rate, duration)
            on_throttled: Callback called when throttled

        Example:
            @throttle_per_target.throttled(
                RateLimit(rate=3, duration=timedelta(hours=1)),
                RateLimit(rate=5, duration=timedelta(days=1)),
                on_throttled=my_callback,
            )
            async def karma_change(...):
                ...
        """
        if not rate_limits:
            raise ValueError("At least one rate limit must be provided")

        def decorator(func):
            @functools.wraps(func)
            async def wrapped(event: TelegramObject, *args, **kwargs):
                # Extract required parameters
                user: User = kwargs["user"]
                chat: Chat = kwargs["chat"]
                target: User = kwargs["target"]
                bot: Bot = kwargs["bot"]

                # Get user's karma power
                user_power = await UserKarma.get_power(user=user, chat=chat)
                now = event.date

                # Check each rate limit
                for rate_limit in rate_limits:
                    # Calculate time window
                    start_time = now - rate_limit.duration

                    # Sum absolute karma changes in this window using DB aggregation
                    result = await (
                        KarmaEvent.filter(
                            user_from=user,
                            chat=chat,
                            user_to=target,
                            date__gte=start_time,
                        )
                        # TODO: use field how_change instead without power?
                        .annotate(total=RawSQL("COALESCE(SUM(ABS(how_match_change)), 0)"))
                        .values_list("total", flat=True)
                    )

                    total_karma_given = result[0] if result else 0

                    # Check if exceeded limit
                    max_allowed = rate_limit.rate * user_power

                    logger.debug(
                        "Throttle per target check: user={user}, chat={chat}, target={target}, "
                        "total_karma={total}, max_allowed={max}, rate={rate}, power={power}",
                        user=user.tg_id,
                        chat=chat.chat_id,
                        target=target.tg_id,
                        total=total_karma_given,
                        max=max_allowed,
                        rate=rate_limit.rate,
                        power=user_power,
                    )

                    if total_karma_given >= max_allowed:
                        logger.info(
                            "User {user} exceeded karma rate limit in chat {chat} for target {target}: "
                            "{total} >= {max} (rate={rate}, power={power})",
                            user=user.tg_id,
                            chat=chat.chat_id,
                            target=target.tg_id,
                            total=total_karma_given,
                            max=max_allowed,
                            rate=rate_limit.rate,
                            power=user_power,
                        )

                        # Call on_throttled callback if provided
                        if on_throttled is not None:
                            await on_throttled(
                                event,
                                user=user,
                                chat=chat,
                                bot=bot,
                                target=target,
                            )

                        # Don't call the original function
                        return None

                # All limits not exceeded, proceed
                logger.debug(
                    "Rate limit per target OK for user {user} in chat {chat} per target {target}",
                    user=user.tg_id,
                    chat=chat.chat_id,
                    target=target.tg_id,
                )
                return await func(event, *args, **kwargs)

            return wrapped

        return decorator

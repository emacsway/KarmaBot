"""
Adaptive throttle decorator using limits library.
"""
import asyncio
import functools
import typing
from datetime import timedelta
from typing import NamedTuple

from aiogram import types
from limits import RateLimitItemPerSecond
from limits.aio.storage import MemoryStorage
from limits.aio.strategies import MovingWindowRateLimiter

from app.infrastructure.database.models import Chat, User
from app.utils.exceptions import Throttled
from app.utils.log import Logger

logger = Logger(__name__)


class RateLimit(NamedTuple):
    """Rate limit configuration."""
    rate: int  # Number of allowed requests
    duration: timedelta  # Time period


class AdaptiveThrottle:
    """
    Adaptive throttle using limits library with in-memory storage.

    Limits are applied per user per chat (separately for each chat).
    """

    def __init__(self):
        self.storage = MemoryStorage()
        self.strategy = MovingWindowRateLimiter(self.storage)

    def _get_identifier(self, *args, **kwargs) -> str:
        """
        Template method for creating rate limit identifier.

        Override this method to customize identifier generation.
        """
        user: User = kwargs["user"]
        chat: Chat = kwargs["chat"]
        key: str = kwargs["key"]
        return f"key:{key}:user:{user.tg_id}:chat:{chat.chat_id}"

    def throttled(
        self,
        *rate_limits: RateLimit,
        key: typing.Optional[str] = None,
        on_throttled: typing.Optional[typing.Callable] = None,
    ):
        """
        Throttle decorator using limits library with multiple rate limits.

        Args:
            *rate_limits: Variable number of RateLimit tuples (rate, duration)
            key: Optional custom key (default: function name)
            on_throttled: Callback called when throttled

        Example:
            @throttled(
                RateLimit(rate=10, duration=timedelta(hours=1)),
                RateLimit(rate=20, duration=timedelta(days=1)),
            )
            async def my_handler(...):
                ...
        """
        if not rate_limits:
            raise ValueError("At least one rate limit must be provided")

        # Convert RateLimit to limits library format
        limit_items = [
            RateLimitItemPerSecond(rl.rate, int(rl.duration.total_seconds()))
            for rl in rate_limits
        ]

        def decorator(func):
            current_key = key if key is not None else func.__name__

            @functools.wraps(func)
            async def wrapped(*args, **kwargs):
                user: User = kwargs["user"]

                # Create unique identifier using template method
                user_identifier = self._get_identifier(*args, key=current_key, **kwargs)

                # Try to acquire all rate limits
                # If any limit is exceeded, handle it immediately
                for limit_item, violated_limit in zip(limit_items, rate_limits):
                    # strategy.hit() returns True if allowed, False if rate limit exceeded
                    if not await self.strategy.hit(limit_item, user_identifier):
                        # Rate limit exceeded
                        logger.info(
                            "User {user} throttled for user_identifier {user_identifier} "
                            "(limit: {rate}/{duration}s)",
                            user=user.tg_id,
                            user_identifier=user_identifier,
                            rate=violated_limit.rate,
                            duration=violated_limit.duration,
                        )

                        # Call on_throttled callback if provided
                        await process_on_throttled(
                            on_throttled,
                            current_key,
                            violated_limit,
                            *args,
                            **kwargs,
                        )
                        # Don't call the original function
                        return None

                # All limits not exceeded, proceed
                logger.debug(
                    "Rate limit OK for user {user}, user_identifier {user_identifier}",
                    user=user.tg_id,
                    user_identifier=user_identifier,
                )
                return await func(*args, **kwargs)

            return wrapped

        return decorator


class AdaptiveThrottlePerTarget(AdaptiveThrottle):
    """
    Adaptive throttle that tracks limits per user per target per chat.

    This allows limiting how often a user can perform actions on specific targets,
    e.g., limiting karma changes to the same user.
    """

    def _get_identifier(self, *args, **kwargs) -> str:
        target: User = kwargs["target"]
        base = super()._get_identifier(*args, **kwargs)
        return f"{base}:target:{target.tg_id}"


async def process_on_throttled(
    on_throttled: typing.Callable,
    key: str,
    violated_limit: RateLimit,
    *args,
    **kwargs,
):
    """Process on_throttled callback when rate limit is exceeded."""
    if on_throttled:
        if asyncio.iscoroutinefunction(on_throttled):
            await on_throttled(*args, **kwargs)
        else:
            on_throttled(*args, **kwargs)
    else:
        # Default behavior: raise Throttled exception
        user: User = kwargs.get("user")
        chat: Chat = kwargs.get("chat")
        raise Throttled(
            key=key,
            chat_id=chat.chat_id if chat else 0,
            user_id=user.tg_id if user else 0,
            rate=violated_limit.rate,
            duration=violated_limit.duration,
        )

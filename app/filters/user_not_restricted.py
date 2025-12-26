"""Filter for checking if user has no active restrictions."""
from dataclasses import dataclass
from datetime import datetime, timezone

from aiogram import types
from aiogram.filters import BaseFilter
from tortoise.expressions import F, RawSQL

from app.infrastructure.database.models import Chat, ModeratorEvent, User
from app.utils.log import Logger

logger = Logger(__name__)


@dataclass
class UserNotRestricted(BaseFilter):
    """
    Filter that checks if user has no active restrictions.

    If user has active restrictions (date + timedelta_restriction >= now()),
    blocks the event.
    """

    async def __call__(
        self,
        reaction: types.MessageReactionUpdated,
        user: User,
        chat: Chat,
    ) -> bool:
        """
        Check if user has no active restrictions.

        Args:
            reaction: Message reaction update event
            user: User who reacted (from DBMiddleware)
            chat: Chat where reaction occurred (from DBMiddleware)

        Returns:
            True if user has no active restrictions, False otherwise
        """
        now = datetime.now(timezone.utc)

        # Check if any active restrictions exist in a single query
        # Convert bigint (microseconds) to INTERVAL and add to date
        # timedelta_restriction is stored as bigint microseconds in DB
        has_active_restrictions = await (
            ModeratorEvent.filter(
                user=user,
                chat=chat,
                timedelta_restriction__isnull=False,  # Only events with duration
            )
            .annotate(
                expiration=F("date") + RawSQL("INTERVAL '1 microsecond' * timedelta_restriction")
            )
            .filter(expiration__gte=now)
            .exists()
        )

        if has_active_restrictions:
            logger.info(
                "User {user} has active restriction in chat {chat}, reaction ignored",
                user=user.tg_id,
                chat=chat.chat_id,
            )
            return False

        return True

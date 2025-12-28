"""Model for storing messages to support reaction-based karma changes."""
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from tortoise import fields
from tortoise.models import Model

if TYPE_CHECKING:
    from app.infrastructure.database.models.chat import Chat
    from app.infrastructure.database.models.user import User


class Message(Model):
    """
    Stores messages for recent messages to enable reaction-based karma changes.

    Since Telegram Bot API doesn't provide message author info in MessageReactionUpdated events,
    we store this information when messages are sent and look it up when processing reactions.

    Records are automatically cleaned up after 90 days to prevent unbounded growth.
    """

    id = fields.IntField(pk=True)
    chat: fields.ForeignKeyRelation["Chat"] = fields.ForeignKeyField(
        "models.Chat", related_name="messages"
    )
    message_id = fields.BigIntField()
    user: fields.ForeignKeyRelation["User"] = fields.ForeignKeyField(
        "models.User", related_name="messages"
    )
    date = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "messages"
        unique_together = (("chat", "message_id"),)
        indexes = (
            ("chat", "message_id"),  # For fast lookups
            ("date",),  # For cleanup queries
        )

    @classmethod
    async def get_author(cls, chat_id: int, message_id: int) -> "User | None":
        """
        Get the author of a message.

        Args:
            chat_id: Database chat ID (not Telegram chat_id)
            message_id: Telegram message ID

        Returns:
            User who authored the message, or None if not found
        """
        record = await cls.filter(chat_id=chat_id, message_id=message_id).select_related("user").first()
        return record.user if record else None

    @classmethod
    async def store_author(cls, chat_id: int, message_id: int, user_id: int, date: datetime) -> "Message":
        """
        Store a message author.

        Args:
            chat_id: Database chat ID (not Telegram chat_id)
            message_id: Telegram message ID
            user_id: Database user ID
            date: Message date from Telegram

        Returns:
            Created or updated Message record
        """
        record, _ = await cls.update_or_create(
            chat_id=chat_id,
            message_id=message_id,
            defaults={"user_id": user_id, "date": date},
        )
        return record

    @classmethod
    async def cleanup_old_records(cls, hours: int = 90*24) -> int:
        """
        Delete records older than specified hours.

        Args:
            hours: Delete records older than this many hours (default: 90*24)

        Returns:
            Number of deleted records
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        deleted_count = await cls.filter(date__lt=cutoff).delete()
        return deleted_count

    def __str__(self):
        return f"Message(chat_id={self.chat_id}, message_id={self.message_id}, user_id={self.user_id})"

    def __repr__(self):
        return str(self)

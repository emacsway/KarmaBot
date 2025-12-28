"""Middleware for storing messages to support reaction-based karma changes."""
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message as TgMessage
from aiogram.types import TelegramObject

from app.infrastructure.database.models import Chat, Message, User
from app.utils.log import Logger

logger = Logger(__name__)


class MessageMiddleware(BaseMiddleware):
    """
    Middleware that stores messages in the database.

    This enables reaction-based karma changes by allowing us to look up
    who authored a message when processing reaction events.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Only process Message events
        if not isinstance(event, TgMessage):
            return await handler(event, data)

        # Only store for group/supergroup messages
        if event.chat.type not in ("group", "supergroup"):
            return await handler(event, data)

        # Get user and chat from DBMiddleware
        user: User | None = data.get("user")
        chat: Chat | None = data.get("chat")

        # Store message author if we have all required data
        if user and chat and event.message_id and event.date:
            try:
                await Message.store_author(
                    chat_id=chat.pk,
                    message_id=event.message_id,
                    user_id=user.pk,
                    date=event.date,
                )
                logger.debug(
                    "Stored message author: chat={chat}, message_id={msg_id}, user={user}",
                    chat=chat.pk,
                    msg_id=event.message_id,
                    user=user.pk,
                )
            except Exception as e:
                # Don't fail the handler if we can't store the author
                logger.warning(
                    "Failed to store message author: {error}",
                    error=e,
                )

        return await handler(event, data)

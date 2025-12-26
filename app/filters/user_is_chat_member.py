"""Filter for checking if user is a chat member."""
from dataclasses import dataclass

from aiogram import Bot, types
from aiogram.enums import ChatMemberStatus
from aiogram.filters import BaseFilter

from app.infrastructure.database.models import Chat, User
from app.utils.log import Logger

logger = Logger(__name__)


@dataclass
class UserIsChatMember(BaseFilter):
    """
    Filter that checks if user is a member of the chat.

    If user is not a chat member, logs the event and blocks it.
    """

    async def __call__(
        self,
        user: User,
        chat: Chat,
        bot: Bot,
    ) -> bool:
        """
        Check if user is a member of the chat.

        Args:
            user: User who reacted (from DBMiddleware)
            chat: Chat where reaction/message occurred (from DBMiddleware)
            bot: Bot instance

        Returns:
            True if user is a chat member, False otherwise
        """
        try:
            member = await bot.get_chat_member(chat.chat_id, user.tg_id)
            is_member = member.status in (
                ChatMemberStatus.CREATOR,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.RESTRICTED,
            )

            if not is_member:
                logger.info(
                    "User {user} is not a member of chat {chat}, karma change is ignored",
                    user=user.tg_id,
                    chat=chat.chat_id,
                )

            return is_member

        except Exception as e:
            logger.warning(
                "Failed to check chat membership for user {user_id} in chat {chat_id}: {error}",
                user_id=user.tg_id,
                chat_id=chat.chat_id,
                error=e,
            )
            return False

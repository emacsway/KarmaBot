"""Filter for extracting target user from message reaction."""
from dataclasses import dataclass

from aiogram import Bot, types
from aiogram.filters import BaseFilter

from app.infrastructure.database.models import Chat, Message, User
from app.models import dto
from app.services.find_target_user import has_target_user
from app.utils.log import Logger

logger = Logger(__name__)


@dataclass
class ReactionHasTargetFilter(BaseFilter):
    """
    Filter that extracts target user (message author) from reaction event.

    Uses message forwarding to determine the original message author.
    Returns empty dict if target cannot be determined, blocking the event.
    """
    can_be_same: bool = False
    can_be_bot: bool = False

    async def __call__(
        self,
        reaction: types.MessageReactionUpdated,
        user: User,
        chat: Chat,
        bot: Bot,
    ) -> dict[str, dto.TargetUser]:
        """
        Extract target user from reaction event.

        Args:
            reaction: Message reaction update event
            user: User who reacted (from DBMiddleware)
            chat: Chat where reaction occurred (from DBMiddleware)
            bot: Bot instance

        Returns:
            Dict with target user if found, empty dict otherwise
        """
        # Get message author from database
        # MessageMiddleware stores authors when messages are sent
        target_user_model = await Message.get_author(
            chat_id=chat.pk,
            message_id=reaction.message_id,
        )

        if target_user_model is None:
            logger.debug(
                "Message author not found in database for chat {chat}, message_id {msg_id}. "
                "Message might be too old or sent before MessageMiddleware was enabled.",
                chat=chat.pk,
                msg_id=reaction.message_id,
            )
            return {}

        # Convert to DTO for has_target_user check
        author_user = dto.TargetUser(
            id=user.tg_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            is_bot=user.is_bot,
        )
        target_user = dto.TargetUser(
            id=target_user_model.tg_id,
            username=target_user_model.username,
            first_name=target_user_model.first_name,
            last_name=target_user_model.last_name,
            is_bot=target_user_model.is_bot,
        )

        # Check if target is valid (not self, not bot, etc.)
        if has_target_user(target_user, author_user, self.can_be_same, self.can_be_bot):
            return {"target": target_user}

        return {}

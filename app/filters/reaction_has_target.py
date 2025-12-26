"""Filter for extracting target user from message reaction."""
from dataclasses import dataclass

from aiogram import Bot, types
from aiogram.filters import BaseFilter

from app.infrastructure.database.models import Chat, User
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
        # Get message to determine its author (target user)
        # NOTE: Telegram Bot API doesn't provide message author info in MessageReactionUpdated
        # We try to forward the message to extract the original sender from forward_origin
        # This requires the bot to have permission to forward messages
        # TODO: Consider implementing a middleware to store message authors in DB for better reliability
        try:
            forwarded = await bot.forward_message(
                chat_id=user.tg_id,
                from_chat_id=chat.chat_id,
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
                    return {}
            # If message wasn't forwarded, it might be from a bot or the original message in the chat
            # We can use the `from` field from the forwarded message
            elif forwarded.from_user and not forwarded.from_user.is_bot:
                target_tg_user = forwarded.from_user

            if target_tg_user is None:
                logger.debug(
                    "Can't determine message author for reaction in chat {chat}",
                    chat=chat.chat_id,
                )
                return {}

        except Exception as e:
            logger.warning(
                "Failed to forward message to get author info: {error}",
                error=e,
            )
            raise
            return {}

        # Convert to DTO and return
        # FixTargetMiddleware will convert this to database User model
        author_user = dto.TargetUser.from_aiogram(reaction.user)
        target_user = dto.TargetUser.from_aiogram(target_tg_user)
        if has_target_user(target_user, author_user, self.can_be_same, self.can_be_bot):
            return {"target": target_user}
        return {}

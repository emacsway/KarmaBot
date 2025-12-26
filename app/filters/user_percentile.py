"""Filter for checking if user is in top percentile by karma."""
import asyncio
from dataclasses import dataclass

from aiogram import Bot, types
from aiogram.filters import BaseFilter
from aiogram.utils.text_decorations import html_decoration as hd

from app.infrastructure.database.models import Chat, User
from app.services.karma_percentile import get_user_percentile
from app.services.remove_message import delete_message
from app.utils.log import Logger

logger = Logger(__name__)


@dataclass
class UserPercentileFilter(BaseFilter):
    """
    Filter that checks if user's karma is in top N percentile.

    If user is not in required percentile, sends informational message
    and blocks the event.
    """

    required_percentile: float = 0.3  # Top 30% by default

    async def __call__(
        self,
        reaction: types.MessageReactionUpdated,
        user: User,
        chat: Chat,
        bot: Bot,
    ) -> bool:
        """
        Check if user's karma is in top percentile.

        Args:
            reaction: Message reaction update event
            user: User who reacted (from DBMiddleware)
            chat: Chat where reaction occurred (from DBMiddleware)
            bot: Bot instance

        Returns:
            True if user is in top percentile, False otherwise
        """
        reactor_percentile = await get_user_percentile(user, chat)

        if reactor_percentile is None or reactor_percentile >= self.required_percentile:
            # User either has no karma or is not in top percentile
            if reactor_percentile is not None:
                # Show informational message for 10 seconds
                try:
                    msg = await bot.send_message(
                        chat_id=reaction.chat.id,
                        text=(
                            f"<b>{hd.quote(user.fullname)}</b>, для изменения кармы с помощью реакций "
                            f"ваша карма должна быть в пределах Tоп-{self.required_percentile * 100:.0f}%, "
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
                percentile=self.required_percentile * 100,
                actual=reactor_percentile * 100 if reactor_percentile is not None else "N/A",
                chat=chat.chat_id,
            )
            return False

        # User is in top percentile
        return True

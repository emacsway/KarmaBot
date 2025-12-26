"""Filter for karma changes via message reactions."""
from dataclasses import dataclass

from aiogram import types
from aiogram.filters import BaseFilter
from aiogram.types import ReactionTypeEmoji

from app.config.karmic_triggers import MINUS_EMOJI, PLUS_EMOJI
from app.infrastructure.database.models import Chat, ChatSettings, UserKarma
from app.infrastructure.database.repo.user import UserRepo

# Reaction coefficient - multiplier applied to reactor's power
# karma_change = sign * reactor_power * REACTION_COEFFICIENT
REACTION_COEFFICIENT = 0.1


def get_karma_change_sign_from_reaction(emoji: str) -> int | None:
    """
    Determine karma change sign from reaction emoji.

    Returns:
        +1 for positive reactions, -1 for negative, None if unknown
    """
    if emoji in PLUS_EMOJI:
        return 1
    if emoji in MINUS_EMOJI:
        return -1
    return None


@dataclass
class KarmaReactionFilter(BaseFilter):
    """
    Filter for message reactions that should change karma.

    Checks if karma counting is enabled, processes reactions,
    and calculates karma change amount.
    """

    async def __call__(
        self,
        reaction: types.MessageReactionUpdated,
        chat_settings: ChatSettings,
        user_repo: UserRepo,
    ) -> dict[str, dict[str, float]]:
        """
        Process message reaction and calculate karma change.

        Args:
            reaction: Message reaction update event
            chat_settings: Chat settings from database
            user_repo: User repository for database operations

        Returns:
            Dict with karma change data or empty dict if reaction should be ignored
        """
        if chat_settings is None or not chat_settings.karma_counting:
            return {}

        # Get or create reactor user
        reactor_user = await user_repo.get_or_create_user(reaction.user)

        # Get or create chat
        chat, _ = await Chat.get_or_create(chat_id=reaction.chat.id)

        # Determine karma changes from added/removed reactions
        karma_change_signs = []

        # Process new reactions (added)
        for new_reaction in reaction.new_reaction:
            if isinstance(new_reaction, ReactionTypeEmoji):
                sign = get_karma_change_sign_from_reaction(new_reaction.emoji)
                if sign is not None:
                    karma_change_signs.append(sign)

        # Process removed reactions (subtract the reverse)
        for old_reaction in reaction.old_reaction:
            if isinstance(old_reaction, ReactionTypeEmoji):
                sign = get_karma_change_sign_from_reaction(old_reaction.emoji)
                if sign is not None:
                    # Reverse the previous change
                    karma_change_signs.append(-sign)

        # If no valid karma changes, return empty dict
        if not karma_change_signs:
            return {}

        # Sum all karma change signs
        total_sign = sum(karma_change_signs)
        if total_sign == 0:  # Ignore if signs cancel out
            return {}

        # Get reactor's power and apply REACTION_COEFFICIENT
        reactor_power = await UserKarma.get_power(reactor_user, chat)
        total_karma_change = total_sign * reactor_power * REACTION_COEFFICIENT

        if abs(total_karma_change) < 0.001:  # Ignore near-zero changes
            return {}

        # Return karma change data
        # chat and user are returned at top level for consistency with karma_change() handler
        return {
            "chat": chat,
            "user": reactor_user,
            "karma_reaction": {
                "karma_change": total_karma_change,
            }
        }

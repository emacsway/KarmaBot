"""Service for checking if user is in top percentile by karma in chat (PostgreSQL optimized)."""
from tortoise import Tortoise

from app.infrastructure.database.models import Chat, User, UserKarma


async def get_user_percentile(user: User, chat: Chat) -> float | None:
    """
    Get user's percentile position in the chat by karma.

    PostgreSQL-optimized version using PERCENT_RANK() window function.

    Args:
        user: User to check
        chat: Chat context

    Returns:
        User's percentile position (0.0 = top, 1.0 = bottom), or None if user has no karma
    """
    # Get user's karma in this chat
    user_karma = await UserKarma.get_or_none(user=user, chat=chat)
    if user_karma is None:
        return None

    # Get connection to execute raw SQL
    conn = Tortoise.get_connection("default")

    # Use PERCENT_RANK() to calculate user's percentile position
    # PERCENT_RANK() OVER (ORDER BY karma DESC) returns percentile where 0 = highest karma
    sql = """
        WITH user_rank AS (
            SELECT
                user_id,
                PERCENT_RANK() OVER (ORDER BY karma DESC) as percentile
            FROM user_karma
            WHERE chat_id = $1
        )
        SELECT percentile FROM user_rank WHERE user_id = $2
    """

    result = await conn.execute_query_dict(sql, [chat.pk, user.pk])

    if not result:
        # User not found in chat
        return None

    return float(result[0]["percentile"])

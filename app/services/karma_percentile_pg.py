"""Service for checking if user is in top percentile by karma in chat (PostgreSQL optimized)."""
from tortoise import Tortoise

from app.infrastructure.database.models import Chat, User, UserKarma


async def is_user_in_top_percentile(user: User, chat: Chat, percentile: float = 0.3) -> bool:
    """
    Check if user's karma is in top N percentile in the chat.

    PostgreSQL-optimized version using percentile_cont() function.

    Args:
        user: User to check
        chat: Chat context
        percentile: Percentile threshold (0.3 = top 30%)

    Returns:
        True if user is in top percentile, False otherwise
    """
    # Get user's karma in this chat
    user_karma = await UserKarma.get_or_none(user=user, chat=chat)
    if user_karma is None:
        return False

    # Get connection to execute raw SQL
    conn = Tortoise.get_connection("default")

    # Calculate threshold karma value for the given percentile
    # If we want top 30%, we need karma >= 70th percentile (1 - 0.3 = 0.7)
    threshold_percentile = 1.0 - percentile

    # Use percentile_cont() to calculate the threshold karma value
    # percentile_cont(0.7) returns the value where 70% of values are below it
    sql = """
        SELECT percentile_cont($1) WITHIN GROUP (ORDER BY karma) AS threshold
        FROM user_karma
        WHERE chat_id = $2
    """

    result = await conn.execute_query_dict(sql, [threshold_percentile, chat.pk])

    if not result or result[0]["threshold"] is None:
        # No users in chat or no karma data
        return False

    threshold = float(result[0]["threshold"])

    # Check if user's karma is above or equal to the threshold
    return user_karma.karma >= threshold

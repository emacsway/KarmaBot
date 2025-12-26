"""Service for checking if user is in top percentile by karma in chat."""
from tortoise import Tortoise

from app.infrastructure.database.models import Chat, User, UserKarma


async def _get_user_percentile_generic(user: User, chat: Chat) -> float | None:
    """
    Get user's percentile position in the chat by karma.

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

    # Get total count of users with karma in this chat
    total_users = await UserKarma.filter(chat=chat).count()
    if total_users == 0:
        return None

    # Get count of users with karma higher than current user
    users_with_higher_karma = await UserKarma.filter(
        chat=chat,
        karma__gt=user_karma.karma
    ).count()

    # Calculate user's position (0 = top, 1 = bottom)
    user_position = users_with_higher_karma / total_users

    return user_position


def _is_postgres_backend() -> bool:
    """Check if the current database backend is PostgreSQL."""
    try:
        conn = Tortoise.get_connection("default")
        # Check if backend is asyncpg (PostgreSQL) or psycopg (PostgreSQL)
        backend_name = conn.__class__.__module__
        return "asyncpg" in backend_name or "psycopg" in backend_name
    except Exception:
        # If we can't determine, use generic implementation
        return False


async def get_user_percentile(user: User, chat: Chat) -> float | None:
    """
    Get user's percentile position in the chat by karma.

    Automatically uses PostgreSQL-optimized implementation if available,
    otherwise falls back to generic implementation.

    Args:
        user: User to check
        chat: Chat context

    Returns:
        User's percentile position (0.0 = top, 1.0 = bottom), or None if user has no karma
    """
    if _is_postgres_backend():
        # Use PostgreSQL-optimized implementation
        from app.services.karma_percentile_pg import get_user_percentile as pg_impl
        return await pg_impl(user, chat)
    else:
        # Use generic implementation
        return await _get_user_percentile_generic(user, chat)

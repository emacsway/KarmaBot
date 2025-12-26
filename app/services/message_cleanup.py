"""Background task for cleaning up old message records."""
import asyncio
from datetime import datetime

from app.infrastructure.database.models import Message
from app.utils.log import Logger

logger = Logger(__name__)


class MessageCleanupTask:
    """Background task that periodically cleans up old message records."""

    def __init__(self, interval_hours: int = 24, retention_hours: int = 90*24):
        """
        Initialize cleanup task.

        Args:
            interval_hours: How often to run cleanup (default: 24 hours)
            retention_hours: Delete records older than this (default: 90*24 hours)
        """
        self.interval_hours = interval_hours
        self.retention_hours = retention_hours
        self._task = None
        self._running = False

    async def _cleanup_loop(self):
        """Main cleanup loop that runs periodically."""
        logger.info(
            "Started message cleanup task (interval={interval}h, retention={retention}h)",
            interval=self.interval_hours,
            retention=self.retention_hours,
        )

        while self._running:
            try:
                # Sleep first to allow bot to fully start
                await asyncio.sleep(self.interval_hours * 3600)

                if not self._running:
                    break

                logger.info("Running message cleanup...")
                deleted_count = await Message.cleanup_old_records(
                    hours=self.retention_hours
                )
                logger.info(
                    "Message cleanup completed: deleted {count} old records",
                    count=deleted_count,
                )

            except asyncio.CancelledError:
                logger.info("Message cleanup task cancelled")
                break
            except Exception as e:
                logger.error(
                    "Error in message cleanup task: {error}",
                    error=e,
                )
                # Continue running despite errors

    def start(self):
        """Start the cleanup task."""
        if self._running:
            logger.warning("Message cleanup task already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._cleanup_loop())
        logger.info("Message cleanup task started")

    async def stop(self):
        """Stop the cleanup task."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("Message cleanup task stopped")

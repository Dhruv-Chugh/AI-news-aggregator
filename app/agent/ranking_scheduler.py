"""24-Hour Recurring Scheduler for Personalized User Interest Ranking Agent.

Uses APScheduler to trigger the personalized ranking cycle every 24 hours.
Supports standalone daemon execution, programmatic lifecycle management,
and immediate execution on startup.
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("ai_news.agent.scheduler")


def run_ranking_job(
    provider: str = "gemini",
    hours: int = 24,
    max_per_source: int = 2,
) -> None:
    """Scheduled task executed every 24 hours."""
    from app.agent.ranking_agent import UserRankingAgent

    logger.info("⏰ Starting scheduled 24-hour personalized ranking cycle...")
    try:
        with UserRankingAgent(preferred_provider=provider) as agent:
            report = agent.run_daily_ranking(hours=hours, max_per_source=max_per_source)
            logger.info(
                "✅ 24-Hour ranking cycle completed: evaluated %d subscribers, persisted %d rankings.",
                report.subscribers_evaluated,
                report.rankings_stored,
            )
    except Exception as e:
        logger.error("❌ Scheduled ranking cycle failed: %s", e, exc_info=True)


class RankingSchedulerService:
    """Manages the background or blocking 24-hour scheduler lifecycle."""

    def __init__(
        self,
        interval_hours: int = 24,
        provider: str = "gemini",
        blocking: bool = True,
        max_per_source: int = 2,
    ) -> None:
        self.interval_hours = interval_hours
        self.provider = provider
        self.blocking = blocking
        self.max_per_source = max_per_source

        scheduler_cls = BlockingScheduler if blocking else BackgroundScheduler
        self.scheduler = scheduler_cls()
        self._is_running = False

    def setup_job(self, run_on_start: bool = True) -> None:
        """Register the 24-hour interval job."""
        trigger = IntervalTrigger(hours=self.interval_hours)
        self.scheduler.add_job(
            run_ranking_job,
            trigger=trigger,
            id="user_interest_ranking_24h",
            name="24-Hour Personalized User Ranking",
            kwargs={
                "provider": self.provider,
                "hours": self.interval_hours,
                "max_per_source": self.max_per_source,
            },
            replace_existing=True,
        )
        logger.info(
            "Registered 24-hour ranking job with interval: every %d hours.",
            self.interval_hours,
        )

        if run_on_start:
            logger.info("Executing initial ranking cycle on startup...")
            run_ranking_job(
                provider=self.provider,
                hours=self.interval_hours,
                max_per_source=self.max_per_source,
            )

    def start(self, run_on_start: bool = True) -> None:
        """Start the scheduler."""
        self.setup_job(run_on_start=run_on_start)
        self._is_running = True
        logger.info(
            "🚀 RankingScheduler started. Next run scheduled in %d hours.",
            self.interval_hours,
        )

        if self.blocking:
            try:
                self.scheduler.start()
            except (KeyboardInterrupt, SystemExit):
                logger.info("RankingScheduler stopped by user.")
                self.stop()
        else:
            self.scheduler.start()

    def stop(self) -> None:
        """Gracefully stop the scheduler."""
        if self._is_running and self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            self._is_running = False
            logger.info("RankingScheduler has been shut down.")


def start_ranking_scheduler(
    interval_hours: int = 24,
    provider: str = "gemini",
    run_on_start: bool = True,
    max_per_source: int = 2,
) -> None:
    """CLI convenience helper to start a blocking 24-hour scheduler daemon."""
    service = RankingSchedulerService(
        interval_hours=interval_hours,
        provider=provider,
        blocking=True,
        max_per_source=max_per_source,
    )

    def handle_sig(sig: int, frame: Any) -> None:
        print("\n🛑 Received shutdown signal. Gracefully stopping 24-hour scheduler...")
        service.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    service.start(run_on_start=run_on_start)


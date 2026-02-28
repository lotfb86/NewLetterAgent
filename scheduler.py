"""APScheduler setup, startup reconciliation, and heartbeat jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import AppConfig
from services.orchestrator import NewsletterOrchestrator

WEEKLY_JOB_ID = "weekly_research_run"
HEARTBEAT_JOB_ID = "agent_heartbeat"


@dataclass
class SchedulerRuntime:
    """Runtime wrapper around APScheduler jobs used by the bot process."""

    config: AppConfig
    orchestrator: NewsletterOrchestrator
    scheduler: BackgroundScheduler | None = None

    def start(self) -> None:
        """Start scheduler jobs and run startup reconciliation."""
        timezone = ZoneInfo(self.config.timezone)
        scheduler = BackgroundScheduler(timezone=timezone)
        scheduler.add_job(
            self._weekly_run_job,
            trigger=CronTrigger(
                day_of_week=self.config.research_day,
                hour=self.config.research_hour,
                minute=0,
                timezone=timezone,
            ),
            id=WEEKLY_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

        scheduler.add_job(
            self._heartbeat_job,
            trigger=IntervalTrigger(hours=24, timezone=timezone),
            id=HEARTBEAT_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        scheduler.start()
        self.scheduler = scheduler

        # Resume in-flight send-stage runs after restart.
        self.orchestrator.resume_incomplete_runs()

    def shutdown(self) -> None:
        """Shutdown scheduler and wait for in-flight jobs to finish."""
        if self.scheduler is None:
            return
        self.scheduler.shutdown(wait=True)
        self.scheduler = None

    def next_weekly_run_at(self) -> datetime | None:
        """Return next scheduled weekly trigger time."""
        if self.scheduler is None:
            return None
        job = self.scheduler.get_job(WEEKLY_JOB_ID)
        if job is None:
            return None
        if job.next_run_time is None:
            return None
        return job.next_run_time.astimezone(UTC)

    def _weekly_run_job(self) -> None:
        self.orchestrator.trigger_run(trigger="scheduled")

    def _heartbeat_job(self) -> None:
        self.orchestrator.post_heartbeat(next_run_at=self.next_weekly_run_at())

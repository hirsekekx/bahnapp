"""Tracker entrypoint: APScheduler driving discovery + poll worker."""
from __future__ import annotations

import logging
import signal
import sys
import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from bahnapp.config import get_settings
from bahnapp.tracker.discovery import mark_completed_jobs, run_discovery_for_active_jobs
from bahnapp.tracker.poller import run_once as poll_once

log = logging.getLogger(__name__)


def main() -> None:
    s = get_settings()
    logging.basicConfig(
        level=getattr(logging, s.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    sched = BackgroundScheduler(timezone=s.tz)
    sched.add_job(
        run_discovery_for_active_jobs,
        trigger=CronTrigger(hour=s.discovery_hour_local, minute=0),
        id="discovery_daily",
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        poll_once,
        trigger=IntervalTrigger(seconds=s.poll_worker_interval_seconds),
        id="poll_worker",
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        mark_completed_jobs,
        trigger=CronTrigger(hour=3, minute=30),
        id="job_completion_check",
        max_instances=1,
        coalesce=True,
    )

    # Run discovery once at startup for robustness after restarts.
    sched.add_job(run_discovery_for_active_jobs, id="discovery_startup")

    sched.start()
    log.info("tracker started, jobs=%s", [j.id for j in sched.get_jobs()])

    stop = False

    def _shutdown(signum, frame):
        nonlocal stop
        log.info("shutdown signal %s", signum)
        stop = True

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        while not stop:
            time.sleep(1)
    finally:
        sched.shutdown(wait=False)
        log.info("tracker stopped")


if __name__ == "__main__":
    sys.exit(main() or 0)

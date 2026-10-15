"""
Foreground agent daemon for continuous background upkeep (PLAN_PHASE3 Section 5.15).

Loops in foreground, runs due jobs at configured intervals, and responds to stop signals.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import datetime

from copilot.config.phase3 import load_runtime_config
from copilot.core.config import PROJECT_ROOT
from copilot.core.timeutil import now_utc
from copilot.models.phase3 import JobRun
from copilot.runtime.runner import run_due_jobs

logger = logging.getLogger(__name__)


def run_agentd(
    conn_factory: Callable[[], sqlite3.Connection],
    user_id: str,
    loop_interval_seconds: int | None = None,
    max_cycles: int | None = None,
    stop_event: threading.Event | None = None,
    clock_fn: Callable[[], datetime] | None = None,
    on_cycle: Callable[[list[JobRun]], None] | None = None,
) -> int:
    """
    Run the foreground agent daemon loop.
    Returns the total number of cycles completed.
    """
    config_path = PROJECT_ROOT / "config" / "runtime.yaml"
    config = load_runtime_config(config_path)

    interval = (
        loop_interval_seconds
        if loop_interval_seconds is not None
        else config.loop_interval_seconds
    )
    cycle = 0

    logger.info("Starting FinCo agentd for user %s (interval=%ss)", user_id, interval)

    conn = conn_factory()
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                logger.info("agentd received stop signal. Exiting.")
                break

            current_time = clock_fn() if clock_fn else now_utc()

            runs = run_due_jobs(
                conn=conn,
                user_id=user_id,
                as_of=current_time,
                config=config,
            )
            if runs:
                logger.info("agentd cycle %d: executed %d jobs", cycle, len(runs))
            if on_cycle:
                on_cycle(runs)

            cycle += 1
            if max_cycles is not None and cycle >= max_cycles:
                logger.info("agentd reached max_cycles=%d. Stopping.", max_cycles)
                break

            # Sleep in short increments to allow rapid stop_event response if interval > 0
            if interval > 0:
                slept = 0.0
                sleep_step = 0.5
                while slept < interval:
                    if stop_event is not None and stop_event.is_set():
                        break
                    time.sleep(min(sleep_step, interval - slept))
                    slept += sleep_step

    except KeyboardInterrupt:
        logger.info("agentd interrupted by user. Shutting down gracefully.")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return cycle

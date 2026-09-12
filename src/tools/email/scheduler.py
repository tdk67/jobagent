"""Recurring background email ingestion scheduler with flexible multi-mode scheduling and observability."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Callable, Dict, Optional

from src.core.config import AppConfig, load_config
from src.core.storage import JobAgentStorage
from src.tools.email_ingest_tool import EmailIngestEngine

log = logging.getLogger(__name__)

WEEKDAY_MAP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def calculate_next_run_time(
    schedule_mode: str = "weekly",
    schedule_day: str = "monday",
    schedule_time: str = "08:00",
    interval_minutes: int = 10080,
    now_dt: Optional[datetime] = None,
) -> datetime:
    """Calculates the exact next timestamp for the configured schedule."""
    now = now_dt or datetime.now(timezone.utc)

    # Parse target time (HH:MM)
    try:
        parts = schedule_time.strip().split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        hour, minute = 8, 0

    mode = (schedule_mode or "weekly").lower()

    if mode in ("weekly", "monday_morning", "weekly_monday"):
        target_weekday = WEEKDAY_MAP.get(schedule_day.lower(), 0)
        cand = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = (target_weekday - now.weekday()) % 7
        if days_ahead == 0 and cand <= now:
            days_ahead = 7
        return cand + timedelta(days=days_ahead)

    elif mode == "daily":
        cand = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if cand <= now:
            cand += timedelta(days=1)
        return cand

    elif mode == "biweekly":
        target_weekday = WEEKDAY_MAP.get(schedule_day.lower(), 0)
        cand = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = (target_weekday - now.weekday()) % 7
        if days_ahead == 0 and cand <= now:
            days_ahead = 14
        else:
            days_ahead = days_ahead if days_ahead > 0 else 14
        return cand + timedelta(days=days_ahead)

    else:
        # Fixed interval mode
        return now + timedelta(minutes=max(1, interval_minutes))


class EmailIngestScheduler:
    """Manages scheduled background execution of email ingestion and provides status observability."""

    def __init__(
        self,
        engine: Optional[EmailIngestEngine] = None,
        storage: Optional[JobAgentStorage] = None,
        config: Optional[AppConfig] = None,
        schedule_mode: str = "weekly",
        schedule_day: str = "monday",
        schedule_time: str = "08:00",
        interval_minutes: int = 10080,
        enabled: bool = True,
    ):
        self.config = config or load_config()
        self.storage = storage or JobAgentStorage(self.config.storage.database_path)
        self.engine = engine or EmailIngestEngine(storage=self.storage, config=self.config)

        self.enabled = enabled
        self.schedule_mode = schedule_mode  # "weekly", "daily", "biweekly", "interval"
        self.schedule_day = schedule_day    # "monday", "tuesday", etc.
        self.schedule_time = schedule_time  # "08:00"
        self.interval_minutes = max(1, interval_minutes)

        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()

        # Observability state
        self.last_run_time: Optional[str] = None
        self.next_run_time: Optional[str] = None
        self.last_status: str = "idle"  # "idle", "running", "success", "error"
        self.last_error: Optional[str] = None
        self.last_result: Optional[Dict[str, Any]] = None
        self.run_count: int = 0

        self._update_next_run_time()

    def _update_next_run_time(self) -> None:
        if not self.enabled:
            self.next_run_time = None
        else:
            next_dt = calculate_next_run_time(
                schedule_mode=self.schedule_mode,
                schedule_day=self.schedule_day,
                schedule_time=self.schedule_time,
                interval_minutes=self.interval_minutes,
            )
            self.next_run_time = next_dt.isoformat()

    def get_status(self) -> Dict[str, Any]:
        """Returns observable telemetry on the recurring ingestion schedule."""
        return {
            "enabled": self.enabled,
            "schedule_mode": self.schedule_mode,
            "schedule_day": self.schedule_day,
            "schedule_time": self.schedule_time,
            "interval_minutes": self.interval_minutes,
            "last_run_time": self.last_run_time,
            "next_run_time": self.next_run_time,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "last_result": self.last_result,
            "run_count": self.run_count,
            "is_busy": self._lock.locked(),
        }

    def update_config(
        self,
        enabled: Optional[bool] = None,
        schedule_mode: Optional[str] = None,
        schedule_day: Optional[str] = None,
        schedule_time: Optional[str] = None,
        interval_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Dynamically reconfigures scheduler parameters."""
        if enabled is not None:
            self.enabled = bool(enabled)
        if schedule_mode is not None:
            self.schedule_mode = str(schedule_mode).lower().strip()
        if schedule_day is not None:
            self.schedule_day = str(schedule_day).lower().strip()
        if schedule_time is not None:
            self.schedule_time = str(schedule_time).strip()
        if interval_minutes is not None:
            self.interval_minutes = max(1, int(interval_minutes))

        self._update_next_run_time()
        log.info(
            "Scheduler config updated: enabled=%s, mode=%s, day=%s, time=%s, interval=%d min, next_run=%s",
            self.enabled,
            self.schedule_mode,
            self.schedule_day,
            self.schedule_time,
            self.interval_minutes,
            self.next_run_time,
        )
        return self.get_status()

    async def run_once(self) -> Dict[str, Any]:
        """Executes a single triage and clustering pass under an async lock."""
        async with self._lock:
            self.last_status = "running"
            self.last_error = None
            run_start = datetime.now(timezone.utc).isoformat()
            log.info("Starting email ingestion triage run at %s...", run_start)

            try:
                # Run ingestion in worker thread to prevent blocking the async event loop
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, self.engine.run_triage)

                self.last_status = "success"
                self.last_run_time = datetime.now(timezone.utc).isoformat()
                self.last_result = result
                self.run_count += 1
                self._update_next_run_time()

                log.info(
                    "Email ingestion run complete: %d scanned, %d confirmations, %d interviews, %d rejections",
                    result.get("total_scanned", 0),
                    result.get("confirmations_found", 0),
                    result.get("interviews_found", 0),
                    result.get("rejections_found", 0),
                )
                return result

            except Exception as exc:
                self.last_status = "error"
                self.last_error = str(exc)
                self.last_run_time = datetime.now(timezone.utc).isoformat()
                self._update_next_run_time()
                log.error("Email ingestion failed with error: %s", exc, exc_info=True)
                return {
                    "error": str(exc),
                    "status": "error",
                    "timestamp": self.last_run_time,
                }

    async def _loop(self) -> None:
        """Background loop waiting until the next scheduled occurrence."""
        log.info(
            "EmailIngestScheduler loop started (mode: %s, next_run: %s)",
            self.schedule_mode,
            self.next_run_time,
        )
        while not self._stop_event.is_set():
            try:
                self._update_next_run_time()
                if not self.enabled or not self.next_run_time:
                    # Paused: wait for stop or config update
                    await asyncio.sleep(10)
                    continue

                target_dt = datetime.fromisoformat(self.next_run_time)
                now_dt = datetime.now(timezone.utc)
                sleep_seconds = max(1.0, (target_dt - now_dt).total_seconds())

                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_seconds)
                    break  # Stop requested
                except asyncio.TimeoutError:
                    pass  # Time to execute scheduled run

                if self.enabled and not self._stop_event.is_set():
                    await self.run_once()

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Scheduler loop encountered unexpected exception: %s", e, exc_info=True)
                await asyncio.sleep(10)

        log.info("EmailIngestScheduler loop stopped")

    def start(self) -> None:
        """Starts the scheduler background task."""
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        """Stops the scheduler background task."""
        self._stop_event.set()
        if self._task:
            self._task.cancel()

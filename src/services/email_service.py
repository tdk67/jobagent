"""Service for email triage, raw SQLite email retrieval, scheduler, and desktop launch."""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, Optional

from src.core.config import AppConfig
from src.core.storage import JobAgentStorage
from src.tools.email.scheduler import EmailIngestScheduler
from src.tools.email_ingest_tool import EmailIngestEngine

log = logging.getLogger(__name__)


class EmailService:
    """Encapsulates all email-related domain logic and integrations."""

    def __init__(
        self,
        storage: JobAgentStorage,
        config: AppConfig,
        scheduler: Optional[EmailIngestScheduler] = None,
    ) -> None:
        self.storage = storage
        self.config = config
        self.engine = EmailIngestEngine(storage=storage, config=config)
        self.scheduler = scheduler or EmailIngestScheduler(
            engine=self.engine,
            storage=storage,
            config=config,
        )

    def triage_inbox(
        self,
        limit: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Runs email triage across connected sources and updates CRM."""
        return self.engine.run_triage(
            limit=limit,
            start_date=start_date,
            end_date=end_date,
        )

    def get_email_details(self, entry_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves email details directly from local SQLite database (zero MAPI overhead)."""
        return self.storage.get_raw_email(entry_id)

    def get_scheduler_status(self) -> Dict[str, Any]:
        """Returns observable telemetry on the recurring email loader."""
        return self.scheduler.get_status()

    async def trigger_scheduler_run(self) -> Dict[str, Any]:
        """Manually triggers immediate email triage."""
        return await self.scheduler.run_once()

    def update_scheduler_config(
        self,
        enabled: Optional[bool] = None,
        schedule_mode: Optional[str] = None,
        schedule_day: Optional[str] = None,
        schedule_time: Optional[str] = None,
        interval_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Updates recurring scheduler configuration."""
        return self.scheduler.update_config(
            enabled=enabled,
            schedule_mode=schedule_mode,
            schedule_day=schedule_day,
            schedule_time=schedule_time,
            interval_minutes=interval_minutes,
        )

    def open_email_in_desktop(self, entry_id: str) -> Dict[str, Any]:
        """Opens corresponding email in Outlook Desktop via native Windows MAPI."""
        if sys.platform != "win32":
            return {
                "status": "unsupported",
                "message": "Desktop email launch is only supported on Windows",
            }

        try:
            import win32com.client  # type: ignore

            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            item = namespace.GetItemFromID(entry_id)
            if not item:
                return {
                    "status": "error",
                    "message": "Email item not found in Outlook store",
                }

            # If Outlook is running headless (no visible Explorer), display Explorer first
            if outlook.Explorers.Count == 0:
                try:
                    exp = item.Parent.GetExplorer()
                    exp.Display()
                except Exception as e_exp:
                    log.debug("Could not show Outlook Explorer: %s", e_exp)

            item.Display()
            try:
                insp = item.GetInspector
                insp.Activate()
            except Exception:
                pass

            # Restore and bring window to foreground
            try:
                import win32con, win32gui  # type: ignore

                def _enum_cb(hwnd, _):
                    if win32gui.IsWindowVisible(hwnd):
                        txt = win32gui.GetWindowText(hwnd)
                        if item.Subject and item.Subject[:25].lower() in txt.lower():
                            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                            win32gui.SetForegroundWindow(hwnd)

                win32gui.EnumWindows(_enum_cb, None)
            except Exception:
                pass

            return {
                "status": "success",
                "message": "Email opened in Outlook Desktop",
                "entry_id": entry_id,
            }
        except Exception as e:
            log.warning("Could not open email %s in Outlook Desktop: %s", entry_id, e)
            return {"status": "error", "message": f"Could not open in Outlook: {e}"}

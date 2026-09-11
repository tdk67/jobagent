from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from strands import tool

from src.core.config import AppConfig, load_config
from src.core.storage import JobAgentStorage
from src.tools.email.adapters import (
    BaseEmailAdapter,
    GmailMcpAdapter,
    ImapAdapter,
    MockEmailAdapter,
    OutlookDesktopAdapter,
)
from src.tools.email.classifier import ClassificationResult, EmailClassifier

log = logging.getLogger(__name__)


class EmailIngestEngine:
    """Orchestrates email ingestion, triage, and storage updates."""

    def __init__(
        self,
        storage: Optional[JobAgentStorage] = None,
        config: Optional[AppConfig] = None,
        adapters: Optional[List[BaseEmailAdapter]] = None,
    ):
        self.config = config or load_config()
        self.storage = storage or JobAgentStorage(self.config.storage.database_path)

        if adapters is not None:
            self.adapters = adapters
        else:
            self.adapters = []
            email_cfg = self.config.email_ingestion

            # 1. Outlook Desktop (MAPI)
            if email_cfg.outlook_desktop.enabled:
                self.adapters.append(OutlookDesktopAdapter(email_cfg.outlook_desktop.folder_names))

            # 2. Gmail via MCP
            if email_cfg.gmail.enabled:
                mcp_client: Optional[Any] = None
                try:
                    # Attempt to construct the MCP client for Gmail (e.g. via a
                    # configured MCP bridge). If none is wired, the adapter would
                    # silently fetch nothing — so we refuse to append a dead adapter.
                    from src.mcp.client import get_mcp_client  # type: ignore[attr-defined]

                    mcp_client = get_mcp_client()
                except Exception:
                    mcp_client = None
                if mcp_client is None:
                    log.warning(
                        "Gmail ingestion enabled in config but no MCP client is wired — "
                        "adapter will fetch nothing",
                    )
                else:
                    self.adapters.append(
                        GmailMcpAdapter(
                            mcp_client=mcp_client,
                            search_query="Bewerbung OR Interview OR Application",
                        )
                    )

            # 3. Generic IMAP
            if email_cfg.generic_imap.enabled:
                import os
                self.adapters.append(
                    ImapAdapter(
                        host=email_cfg.generic_imap.host,
                        port=email_cfg.generic_imap.port,
                        username=os.getenv("IMAP_USER", ""),
                        password=os.getenv("IMAP_PASSWORD", ""),
                        use_ssl=email_cfg.generic_imap.use_ssl,
                    )
                )

    def run_triage(
        self,
        limit: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Runs email extraction across all adapters, classifies, and updates CRM storage."""
        # 1. Load current applications for dual-signal matching
        applied_apps = self.storage.list_applications()
        comp_map = {
            app["company"].strip().lower(): app
            for app in applied_apps
            if app.get("company") and len(app["company"]) >= 3
        }

        classifier = EmailClassifier(applied_companies=comp_map)

        results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "start_date": start_date,
            "end_date": end_date,
            "total_scanned": 0,
            "confirmations_found": 0,
            "interviews_found": 0,
            "rejections_found": 0,
            "noise_filtered": 0,
            "actionable_alerts": [],
        }

        for adapter in self.adapters:
            try:
                emails = adapter.fetch_emails(limit=limit, start_date=start_date, end_date=end_date)
            except Exception as e:
                log.warning("Failed to fetch emails via adapter %s: %s", adapter.__class__.__name__, e, exc_info=True)
                continue

            for item in emails:
                results["total_scanned"] += 1
                classification = classifier.classify(
                    subject=item.subject,
                    body=item.body,
                    sender_name=item.sender_name,
                    sender_email=item.sender_email,
                    enable_llm_fallback=self.config.email_ingestion.llm_fallback,
                )

                # Match with application record if possible
                matched_app = None
                if classification.matched_company:
                    matched_app = comp_map.get(classification.matched_company.lower())

                app_id = matched_app["id"] if matched_app else None

                # Store interaction
                self.storage.record_email_interaction(
                    entry_id=item.entry_id,
                    category=classification.category,
                    sender_name=item.sender_name,
                    sender_email=item.sender_email,
                    subject=item.subject,
                    received_time=item.received_time,
                    preview=item.preview,
                    application_id=app_id,
                    confidence_score=classification.confidence,
                    action_taken=classification.explanation,
                )

                if classification.category == "interview_invitation":
                    results["interviews_found"] += 1
                    comp_name = classification.matched_company or item.sender_name or "Unknown Company"
                    interview_scheduled = classification.suggested_date or item.received_time
                    notes = f"Detected from email: {item.subject}"
                    if classification.suggested_date:
                        notes += f" (Scheduled: {classification.suggested_date})"

                    res = self.storage.record_interview(
                        company=comp_name,
                        interview_date=interview_scheduled,
                        role=classification.matched_role or "Software Engineer",
                        application_id=app_id,
                        interview_type="Interview Invitation",
                        meeting_link=classification.meeting_link,
                        status="Pending_Confirmation",
                        notes=notes,
                        entry_id=item.entry_id,
                    )
                    interview_id, created = res if isinstance(res, tuple) else (res, True)
                    # H5: Alert only when record_interview actually inserted a new record
                    if created:
                        results["actionable_alerts"].append({
                            "type": "interview_invitation",
                            "interview_id": interview_id,
                            "company": comp_name,
                            "subject": item.subject,
                            "meeting_link": classification.meeting_link,
                            "scheduled_date": interview_scheduled,
                        })

                elif classification.category == "rejection":
                    results["rejections_found"] += 1
                    if app_id:
                        self.storage.update_application_status(
                            app_id, "Rejected", notes=f"Rejection email received on {item.received_time}"
                        )

                elif classification.category == "application_confirmation":
                    results["confirmations_found"] += 1
                    # Auto-discover and log applied company if not already tracked!
                    if not matched_app and classification.matched_company:
                        self.storage.upsert_application(
                            company=classification.matched_company,
                            role=classification.matched_role or "Candidate",
                            applied_date=item.received_time,
                            status="Applied",
                            source="Email Ingestion",
                        )

                elif classification.category == "noise":
                    results["noise_filtered"] += 1

        return results


@tool(name="ingest_emails", description="Ingests and classifies incoming job search emails from Outlook or IMAP.")
def ingest_emails(
    limit: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """Ingests job search emails from connected inboxes, classifies them into interviews, rejections, or confirmations, and updates local private storage.

    Parameters:
        limit: Maximum number of emails to scan.
        start_date: Optional start date for date range filtering (e.g. '2026-07-01' or '1-Jul').
        end_date: Optional end date for date range filtering (e.g. '2026-07-07').

    Returns:
        A JSON summary of the triage results and any actionable alerts.
    """
    engine = EmailIngestEngine()
    results = engine.run_triage(limit=limit, start_date=start_date, end_date=end_date)
    return json.dumps(results, indent=2)


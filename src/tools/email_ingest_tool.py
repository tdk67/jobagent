from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.config import AppConfig, load_config
from src.core.storage import JobAgentStorage
from src.tools.email.adapters import (
    BaseEmailAdapter,
    EmailRecord,
    GmailMcpAdapter,
    ImapAdapter,
    MockEmailAdapter,
    OutlookDesktopAdapter,
)
from src.tools.email.classifier import ClassificationResult, EmailClassifier
from src.tools.email.clustering import ApplicationClusterer

log = logging.getLogger(__name__)


class EmailIngestEngine:
    """Orchestrates email fetching, raw email persistence, deduplication, and application clustering."""

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

    def fetch_and_cache_emails(
        self,
        limit: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[EmailRecord]:
        """Fetches emails from all adapters and persists raw messages to SQLite raw_emails table."""
        all_emails: List[EmailRecord] = []
        for adapter in self.adapters:
            try:
                emails = adapter.fetch_emails(limit=limit, start_date=start_date, end_date=end_date)
            except Exception as e:
                log.warning("Failed to fetch emails via %s: %s", adapter.__class__.__name__, e, exc_info=True)
                continue

            for item in emails:
                actual_folder = item.folder or ("Bewerbung" if isinstance(adapter, OutlookDesktopAdapter) else "Inbox")
                self.storage.save_raw_email(
                    entry_id=item.entry_id,
                    folder=actual_folder,
                    sender_name=item.sender_name,
                    sender_email=item.sender_email,
                    subject=item.subject,
                    body=item.body,
                    preview=item.preview,
                    received_time=item.received_time,
                )
                all_emails.append(item)

        return all_emails

    def run_triage(
        self,
        limit: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetches connected inboxes, persists raw emails, and applies canonical clustering and deduplication."""
        # 1. Fetch & Cache raw emails
        fetched_emails = self.fetch_and_cache_emails(limit=limit, start_date=start_date, end_date=end_date)

        # 2. Cluster & deduplicate
        clusterer = ApplicationClusterer(storage=self.storage)
        batch_res = clusterer.cluster_batch(
            records=fetched_emails,
            folder="Bewerbung",
            enable_llm_fallback=self.config.email_ingestion.llm_fallback,
        )

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "start_date": start_date,
            "end_date": end_date,
            "total_scanned": batch_res["total_processed"],
            "confirmations_found": batch_res["confirmations"],
            "interviews_found": batch_res["interviews"],
            "rejections_found": batch_res["rejections"],
            "noise_filtered": batch_res["noise"],
            "actionable_alerts": batch_res["actionable_alerts"],
        }

    def cluster_cached_emails(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        folder: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Runs fast offline clustering on already downloaded raw emails in raw_emails table."""
        raw_list = self.storage.list_raw_emails(start_date=start_date, end_date=end_date, folder=folder)
        records: List[EmailRecord] = [
            EmailRecord(
                entry_id=r["entry_id"],
                sender_name=r["sender_name"] or "",
                sender_email=r["sender_email"] or "",
                subject=r["subject"] or "",
                received_time=r["received_time"] or "",
                body=r["body"] or "",
                preview=r["preview"] or "",
                folder=r.get("folder") or folder or "Bewerbung",
            )
            for r in raw_list
        ]

        clusterer = ApplicationClusterer(storage=self.storage)
        batch_res = clusterer.cluster_batch(
            records=records,
            folder=folder or "Bewerbung",
            enable_llm_fallback=self.config.email_ingestion.llm_fallback,
        )

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_cached_processed": len(records),
            "confirmations_found": batch_res["confirmations"],
            "interviews_found": batch_res["interviews"],
            "rejections_found": batch_res["rejections"],
            "noise_filtered": batch_res["noise"],
            "actionable_alerts": batch_res["actionable_alerts"],
        }
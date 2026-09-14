from __future__ import annotations

import html
import ipaddress
import json
import logging
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from src.core.config import AppConfig, load_config
from src.core.storage import JobAgentStorage
from src.tools.archive.extractor import JobContentExtractor

log = logging.getLogger(__name__)


from src.tools.archive.url_guard import is_safe_url


class JobArchiveEngine:
    """Preserves job postings as clean Markdown stored in the local CRM database."""

    def __init__(
        self,
        storage: Optional[JobAgentStorage] = None,
        config: Optional[AppConfig] = None,
    ):
        self.config = config or load_config()
        self.storage = storage or JobAgentStorage(self.config.storage.database_path)
        self.extractor = JobContentExtractor()

    def _sanitize_name(self, name: str) -> str:
        s = re.sub(r"[^\w\-_.]", "_", name.strip())
        return re.sub(r"_+", "_", s)[:50]

    def archive(
        self,
        company: str,
        role: str,
        job_url: Optional[str] = None,
        raw_html: Optional[str] = None,
        qa_pairs: Optional[Dict[str, str]] = None,
        status: str = "Saved",
    ) -> Dict[str, Any]:
        """Archives a job posting as clean Markdown stored in the CRM database."""
        # 1. Produce Markdown
        if raw_html:
            md_content = self.extractor.to_markdown(raw_html, title=role, company=company)
            metadata = self.extractor.extract_metadata(raw_html)
        else:
            md_content = f"# {html.escape(role)}\n**Company:** {html.escape(company)}\n**URL:** {html.escape(job_url or 'N/A')}\n\n[Archived via JobAgent]"
            metadata = {"salary": None, "location": None, "work_model": None}

        # 2. Store QA Pairs into Memory
        if qa_pairs:
            for q, a in qa_pairs.items():
                self.storage.save_qa_answer(question=q, answer=a, category="screening")

        # 3. Upsert application in CRM database (job_description_md stored in DB)
        app_id = self.storage.upsert_application(
            company=company,
            role=role,
            applied_date=datetime.now(timezone.utc).isoformat(),
            status=status,
            job_url=job_url,
            salary_info=metadata.get("salary"),
            location=metadata.get("location") or metadata.get("work_model"),
            notes=None,
            job_description_md=md_content,
        )

        return {
            "application_id": app_id,
            "company": company,
            "role": role,
            "markdown_stored": True,
            "md_preview": md_content[:500] + ("…" if len(md_content) > 500 else ""),
            "metadata": metadata,
        }

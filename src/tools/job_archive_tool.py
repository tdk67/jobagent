from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from strands import tool

from src.core.config import AppConfig, load_config
from src.core.storage import JobAgentStorage
from src.tools.archive.extractor import JobContentExtractor
from src.tools.archive.snapshotter import JobSnapshotter

log = logging.getLogger(__name__)


def is_safe_url(url: str) -> bool:
    """Validates URL to protect against SSRF (disallow private IP ranges, localhost, DNS rebinding)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = (parsed.hostname or "").lower().strip()
        if not hostname or hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return False
        if hostname.endswith(".local") or hostname.endswith(".internal"):
            return False
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        except ValueError:
            # Resolve DNS to check underlying IP addresses against private ranges
            try:
                addr_info = socket.getaddrinfo(hostname, None)
                for item in addr_info:
                    resolved_ip_str = item[4][0]
                    resolved_ip = ipaddress.ip_address(resolved_ip_str)
                    if resolved_ip.is_private or resolved_ip.is_loopback or resolved_ip.is_link_local or resolved_ip.is_reserved or resolved_ip.is_multicast:
                        return False
            except socket.gaierror:
                return False
        return True
    except Exception:
        return False


class JobArchiveEngine:
    """Preserves dual-asset archives: Clean Markdown + High-Resolution PDF Snapshot."""

    def __init__(
        self,
        storage: Optional[JobAgentStorage] = None,
        config: Optional[AppConfig] = None,
    ):
        self.config = config or load_config()
        self.storage = storage or JobAgentStorage(self.config.storage.database_path)
        self.extractor = JobContentExtractor()
        self.snapshotter = JobSnapshotter(output_dir=self.config.storage.snapshot_dir)
        self.archive_dir = Path(self.config.storage.archive_dir)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

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
    ) -> Dict[str, Any]:
        """Archives a job posting into Markdown and PDF snapshot, and records to database."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        prefix = f"{self._sanitize_name(company)}_{self._sanitize_name(role)}_{timestamp}"

        md_filename = f"{prefix}.md"
        pdf_filename = f"{prefix}.pdf"

        md_path = self.archive_dir / md_filename
        pdf_full_path: Optional[str] = None

        # 1. Produce Markdown
        if raw_html:
            md_content = self.extractor.to_markdown(raw_html, title=role, company=company)
            metadata = self.extractor.extract_metadata(raw_html)
        else:
            md_content = f"# {role}\n**Company:** {company}\n**URL:** {job_url or 'N/A'}\n\n[Archived via JobAgent]"
            metadata = {"salary": None, "location": None, "work_model": None}

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        # 2. Produce PDF Snapshot
        try:
            if raw_html:
                # Clean HTML first to neutralize any malicious XSS scripts/iframes before Playwright renders
                cleaned_html = self.extractor.clean_html(raw_html)
                pdf_full_path = self.snapshotter.capture_from_html(cleaned_html, pdf_filename)
            elif job_url:
                if is_safe_url(job_url):
                    pdf_full_path = self.snapshotter.capture_from_url(job_url, pdf_filename)
                else:
                    log.warning("SSRF security guard: rejected unsafe URL '%s'", job_url)
                    pdf_full_path = None
        except Exception as e:
            log.warning("PDF snapshot generation failed for %s - %s: %s", company, role, e, exc_info=True)
            pdf_full_path = None

        # 3. Store QA Pairs into Memory
        if qa_pairs:
            for q, a in qa_pairs.items():
                self.storage.save_qa_answer(question=q, answer=a, category="screening")

        # 4. Upsert application in CRM database
        app_id = self.storage.upsert_application(
            company=company,
            role=role,
            applied_date=datetime.now(timezone.utc).isoformat(),
            status="Applied",
            job_url=job_url,
            salary_info=metadata.get("salary"),
            location=metadata.get("location") or metadata.get("work_model"),
            notes=f"Archived: {md_filename}",
        )

        return {
            "application_id": app_id,
            "company": company,
            "role": role,
            "markdown_path": str(md_path.resolve()),
            "snapshot_pdf_path": pdf_full_path,
            "metadata": metadata,
        }


@tool(name="archive_job_posting", description="Preserves a job posting as clean Markdown and visual PDF snapshot.")
def archive_job_posting(
    company: str,
    role: str,
    job_url: Optional[str] = None,
    raw_html: Optional[str] = None,
) -> str:
    """Archives a job posting into clean Markdown text and full-page PDF snapshot for interview preparation and compliance.

    Parameters:
        company: Name of the hiring company.
        role: Title of the position.
        job_url: Web address of the job post.
        raw_html: Optional DOM HTML content of the job post.

    Returns:
        JSON string with paths to the archived assets and CRM entry ID.
    """
    engine = JobArchiveEngine()
    result = engine.archive(company=company, role=role, job_url=job_url, raw_html=raw_html)
    return json.dumps(result, indent=2)

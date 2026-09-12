"""Service for archiving job postings with dual-asset (Markdown + PDF) snapshots."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.core.config import AppConfig
from src.core.storage import JobAgentStorage
from src.tools.job_archive_tool import JobArchiveEngine

log = logging.getLogger(__name__)


class ArchiveService:
    """Encapsulates job archiving operations."""

    def __init__(self, storage: JobAgentStorage, config: AppConfig) -> None:
        self.storage = storage
        self.config = config
        self.engine = JobArchiveEngine(storage=storage, config=config)

    def archive(
        self,
        company: str,
        role: str,
        job_url: Optional[str] = None,
        raw_html: Optional[str] = None,
        qa_pairs: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Archives a job posting into clean Markdown and high-res PDF snapshot."""
        return self.engine.archive(
            company=company,
            role=role,
            job_url=job_url,
            raw_html=raw_html,
            qa_pairs=qa_pairs,
        )

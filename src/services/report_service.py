"""Service for generating compliance reports, AfA tables, and HTML dashboards."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.core.config import AppConfig
from src.core.profile import CandidateProfile
from src.core.storage import JobAgentStorage
from src.tools.report_render_tool import ReportRenderEngine

log = logging.getLogger(__name__)


class ReportService:
    """Encapsulates report generation and export logic."""

    def __init__(
        self,
        storage: JobAgentStorage,
        config: AppConfig,
        profile: CandidateProfile,
    ) -> None:
        self.storage = storage
        self.config = config
        self.profile = profile
        self.engine = ReportRenderEngine(storage=storage, profile=profile, config=config)

    def generate(
        self,
        view_type: str = "dashboard",
        export_pdf: bool = True,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        report_period: Optional[str] = None,
        output_pdf_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generates statutory proof tables, dashboards, and PDF exports."""
        return self.engine.generate(
            view_type=view_type,
            export_pdf=export_pdf,
            start_date=start_date,
            end_date=end_date,
            report_period=report_period,
            output_pdf_name=output_pdf_name,
        )

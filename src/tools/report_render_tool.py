"""Strands Agent tool for generating multi-stakeholder compliance reports and dashboards."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.config import AppConfig, load_config
from src.core.profile import CandidateProfile, load_profile
from src.core.storage import JobAgentStorage
from src.tools.report.generator import ReportGenerator


class ReportRenderEngine:
    """Orchestrates summary data extraction, profile enrichment, and report generation."""

    def __init__(
        self,
        storage: Optional[JobAgentStorage] = None,
        profile: Optional[CandidateProfile] = None,
        config: Optional[AppConfig] = None,
    ):
        self.config = config or load_config()
        self.storage = storage or JobAgentStorage(self.config.storage.database_path)
        self.profile = profile or load_profile()
        self.generator = ReportGenerator(
            template_dir="templates",
            output_dir=self.config.reporting.output_dir,
        )

    def generate(
        self,
        view_type: str = "dashboard",
        export_pdf: bool = True,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None,
        report_period: Optional[str] = None,
        output_pdf_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generates HTML and optional PDF for the requested view with date filtering."""
        summary = self.storage.export_summary_json(
            start_date=start_date,
            end_date=end_date,
            report_period=report_period,
        )

        # Context enrichment with candidate profile (no hardcoding)
        context = {
            **summary,
            "candidate_name": self.profile.personal.fullName,
            "candidate_email": self.profile.personal.email,
            "candidate_phone": self.profile.personal.phone,
            "candidate_address": self.profile.personal.address,
            "candidate_role": (
                self.profile.preferences.targetRoles[0]
                if self.profile.preferences.targetRoles
                else "Software Engineer"
            ),
        }

        html_path = self.generator.render_html(view_type=view_type, data=context)
        pdf_path = None

        if export_pdf and self.config.reporting.enable_pdf_export:
            landscape = view_type == "afa_table"
            pdf_name = output_pdf_name or f"{view_type}_report.pdf"
            pdf_path = self.generator.convert_html_to_pdf(
                html_file_path=html_path,
                output_pdf_name=pdf_name,
                landscape=landscape,
            )

        return {
            "view_type": view_type,
            "report_period": summary.get("report_period"),
            "start_date": summary.get("start_date"),
            "end_date": summary.get("end_date"),
            "html_path": html_path,
            "pdf_path": pdf_path,
            "total_applications": summary.get("total_count", 0),
            "applications_count": summary.get("total_count", 0),
        }

    def generate_weekly_reports(
        self,
        start_date: str = "2026-07-01",
        end_date: Optional[str] = None,
        view_type: str = "afa_table",
    ) -> List[Dict[str, Any]]:
        """Generates separate weekly reports week-by-week between start_date and end_date."""
        from datetime import date, datetime, timedelta, timezone
        from src.utils.date_utils import parse_flexible_date

        s_str = parse_flexible_date(start_date) or "2026-07-01"
        e_str = parse_flexible_date(end_date) or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        cur_start = datetime.strptime(s_str, "%Y-%m-%d").date()
        target_end = datetime.strptime(e_str, "%Y-%m-%d").date()

        reports: List[Dict[str, Any]] = []
        while cur_start <= target_end:
            days_to_sunday = 6 - cur_start.weekday()
            cur_end = min(cur_start + timedelta(days=days_to_sunday), target_end)

            week_num = cur_start.isocalendar()[1]
            period_label = f"KW {week_num:02d} ({cur_start.strftime('%d.%m.%Y')} – {cur_end.strftime('%d.%m.%Y')})"
            filename = f"{view_type}_KW{week_num:02d}_{cur_start.strftime('%Y%m%d')}_{cur_end.strftime('%Y%m%d')}.pdf"

            res = self.generate(
                view_type=view_type,
                export_pdf=True,
                start_date=cur_start.strftime("%Y-%m-%d"),
                end_date=cur_end.strftime("%Y-%m-%d"),
                report_period=period_label,
                output_pdf_name=filename,
            )
            reports.append(res)

            # Advance to next Monday
            cur_start = cur_end + timedelta(days=1)

        return reports

    def generate_all_views(
        self,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Generates all configured reports (Dashboard, German AfA table, Agency summary)."""
        reports = {}
        for view in self.config.reporting.default_views:
            reports[view] = self.generate(
                view_type=view,
                export_pdf=True,
                start_date=start_date,
                end_date=end_date,
            )
        return reports
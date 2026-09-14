"""Statistics and analytics repository for JobAgent.

Handles:
- Funnel metrics, conversion KPIs, and weekly activity timelines.
- Parameterized SQL filtering to eliminate SQL interpolation patterns (S6).
- Structured export preparation for Jinja2 dashboards and statutory AfA reporting.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from src.core.storage.base import BaseStorage
from src.utils.date_utils import parse_flexible_date

log = logging.getLogger(__name__)


class StatisticsRepo(BaseStorage):
    """Repository providing statistical aggregations and reporting summaries."""

    def _build_date_filter_clause(
        self,
        date_column: str,
        start_date: Optional[Union[str, datetime, date]] = None,
        end_date: Optional[Union[str, datetime, date]] = None,
    ) -> Tuple[str, List[Any]]:
        """Builds a safe parameterized WHERE fragment for date range filtering."""
        norm_start = parse_flexible_date(start_date) if start_date else None
        norm_end = parse_flexible_date(end_date) if end_date else None

        clauses: List[str] = []
        params: List[Any] = []

        if norm_start:
            clauses.append(f"substr({date_column}, 1, 10) >= ?")
            params.append(norm_start)
        if norm_end:
            clauses.append(f"substr({date_column}, 1, 10) <= ?")
            params.append(norm_end)

        if not clauses:
            return ("", [])
        return (" AND " + " AND ".join(clauses), params)

    def get_statistics(
        self,
        start_date: Optional[Union[str, datetime, date]] = None,
        end_date: Optional[Union[str, datetime, date]] = None,
    ) -> Dict[str, Any]:
        """Calculates funnel KPIs and weekly aggregation with safe parameterized date filtering."""
        date_clause, date_params = self._build_date_filter_clause("applied_date", start_date, end_date)

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Total applications
            cursor.execute(f"SELECT COUNT(*) as total FROM applications WHERE 1=1{date_clause}", date_params)
            total_apps = cursor.fetchone()["total"]

            # Total interviews
            cursor.execute(
                f"SELECT COUNT(*) as count FROM applications WHERE LOWER(status) = 'interview'{date_clause}",
                date_params,
            )
            total_interviews = cursor.fetchone()["count"]

            # Total rejections
            cursor.execute(
                f"SELECT COUNT(*) as count FROM applications WHERE LOWER(status) = 'rejected'{date_clause}",
                date_params,
            )
            total_rejections = cursor.fetchone()["count"]

            # Total pending / applied
            cursor.execute(
                f"SELECT COUNT(*) as count FROM applications WHERE LOWER(status) = 'applied'{date_clause}",
                date_params,
            )
            total_pending = cursor.fetchone()["count"]

            response_rate = round((total_interviews / total_apps * 100), 1) if total_apps > 0 else 0.0
            rejection_rate = round((total_rejections / total_apps * 100), 1) if total_apps > 0 else 0.0

            cursor.execute(f"""
                SELECT strftime('%Y-W%W', applied_date) as week, COUNT(*) as count
                FROM applications WHERE 1=1{date_clause}
                GROUP BY week
                ORDER BY week ASC
            """, date_params)
            weekly_data = [dict(row) for row in cursor.fetchall()]

            return {
                "total_applications": total_apps,
                "total_interviews": total_interviews,
                "total_rejections": total_rejections,
                "total_pending": total_pending,
                "response_rate_percent": response_rate,
                "rejection_rate_percent": rejection_rate,
                "weekly_activity": weekly_data,
            }

    def export_summary_json(
        self,
        start_date: Optional[Union[str, datetime, date]] = None,
        end_date: Optional[Union[str, datetime, date]] = None,
        report_period: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Exports a complete structured summary ready for Jinja2 rendering."""
        stats = self.get_statistics(start_date=start_date, end_date=end_date)
        # Note: self.list_applications and self.list_interviews are provided by the unified class
        apps = getattr(self, "list_applications")(start_date=start_date, end_date=end_date)
        interviews = getattr(self, "list_interviews")(start_date=start_date, end_date=end_date)

        norm_s = parse_flexible_date(start_date) if start_date else None
        norm_e = parse_flexible_date(end_date) if end_date else None

        if not report_period:
            if norm_s and norm_e:
                report_period = f"{norm_s} bis {norm_e}"
            elif norm_s:
                report_period = f"Ab {norm_s}"
            elif norm_e:
                report_period = f"Bis {norm_e}"
            else:
                report_period = "Gesamtzeitraum"

        # Batch-fetch email interactions for traceability
        app_emails_map: Dict[int, List[Dict[str, Any]]] = {}
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 
                    e.application_id, 
                    e.entry_id, 
                    e.category, 
                    e.intent,
                    e.confidence_score,
                    e.reasoning,
                    e.subject, 
                    e.received_time, 
                    e.sender_name, 
                    e.sender_email, 
                    e.preview,
                    COALESCE(r.body, e.preview) AS body
                FROM email_interactions e
                LEFT JOIN raw_emails r ON e.entry_id = r.entry_id
                WHERE e.application_id IS NOT NULL 
                ORDER BY e.received_time ASC
                """
            )
            for r in cursor.fetchall():
                aid = r["application_id"]
                app_emails_map.setdefault(aid, []).append(dict(r))

        # Ensure default sort is most recent application time (fallback to latest email received_time, then created_at)
        def get_app_sort_time(app_row: Dict[str, Any]) -> str:
            d = app_row.get("applied_date")
            if d and d != "—":
                return str(d)
            aid = app_row.get("id")
            linked_emails = app_emails_map.get(aid, [])
            if linked_emails:
                return str(linked_emails[-1].get("received_time") or "")
            return str(app_row.get("created_at") or "")

        sorted_apps = sorted(apps, key=get_app_sort_time, reverse=True)

        # Format applications for German AfA statutory format and dashboards
        formatted_apps = []
        for idx, app in enumerate(sorted_apps, 1):
            applied_dt_str = app.get("applied_date", "")
            raw_sort_dt = get_app_sort_time(app)
            try:
                dt = datetime.fromisoformat(applied_dt_str.replace("Z", "+00:00"))
                display_date = dt.strftime("%d.%m.%Y")
            except Exception as e:
                log.debug("Date parse fallback for %s: %s", applied_dt_str, e)
                display_date = applied_dt_str[:10] if applied_dt_str else ""
                if not display_date and raw_sort_dt:
                    display_date = raw_sort_dt[:10]

            app_id = app.get("id")
            linked = app_emails_map.get(app_id, [])
            entry_ids = [m["entry_id"] for m in linked if m.get("entry_id")]
            has_interview = any(m.get("category") == "interview_invitation" for m in linked) or any(
                str(app_id) == str(it.get("application_id")) for it in interviews
            )

            formatted_apps.append({
                "index": idx,
                "id": app_id,
                "company": app.get("company", "—"),
                "role": app.get("role", "—"),
                "applied_date": display_date,
                "raw_date": raw_sort_dt,
                "status": app.get("status", "Applied"),
                "had_interview": has_interview,
                "source": app.get("source", "Direct"),
                "location": app.get("location") or "—",
                "notes": app.get("notes") or "",

                "job_url": app.get("job_url") or "",
                "email_count": len(linked),
                "emails": linked,
                "entry_ids": entry_ids,
                "primary_entry_id": entry_ids[0] if entry_ids else "",
            })

        return {
            "generated_at": datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC"),
            "report_period": report_period,
            "start_date": norm_s,
            "end_date": norm_e,
            "statistics": stats,
            "applications": formatted_apps,
            "interviews": interviews,
            "total_count": len(formatted_apps),
        }

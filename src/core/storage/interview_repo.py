"""Interview management repository for JobAgent.

Handles:
- Idempotent recording of interview invitations and meeting links.
- Updating application status to 'Interview' automatically.
- Date filtering and upcoming interview listings.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from src.core.storage.base import BaseStorage
from src.utils.date_utils import parse_flexible_date

log = logging.getLogger(__name__)


class InterviewRepo(BaseStorage):
    """Repository handling scheduled interviews and calendar events."""

    def record_interview(
        self,
        company: str,
        interview_date: str,
        role: Optional[str] = None,
        application_id: Optional[int] = None,
        interview_type: str = "Interview",
        meeting_link: Optional[str] = None,
        status: str = "Scheduled",
        notes: Optional[str] = None,
        entry_id: Optional[str] = None,
    ) -> Tuple[int, bool]:
        """Records a scheduled interview idempotently.
        Returns a tuple of (interview_id, created) to prevent duplicate alerts on re-ingest cycles.
        """
        clean_company = company.strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. Deduplication check by entry_id
            if entry_id:
                cursor.execute("SELECT id FROM interviews WHERE entry_id = ?", (entry_id,))
                existing = cursor.fetchone()
                if existing:
                    return (existing["id"], False)

            # 2. Deduplication check by company and interview date
            cursor.execute(
                "SELECT id FROM interviews WHERE LOWER(company) = LOWER(?) AND interview_date = ?",
                (clean_company, interview_date),
            )
            existing = cursor.fetchone()
            if existing:
                return (existing["id"], False)

            cursor.execute(
                """
                INSERT INTO interviews (application_id, entry_id, company, role, interview_date, interview_type, meeting_link, status, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (application_id, entry_id, clean_company, role, interview_date, interview_type, meeting_link, status, notes),
            )
            interview_id = cursor.lastrowid

            if application_id:
                cursor.execute("UPDATE applications SET status = 'Interview' WHERE id = ?", (application_id,))
            else:
                # Find matching application by company
                cursor.execute("SELECT id FROM applications WHERE LOWER(company) = LOWER(?)", (clean_company,))
                row = cursor.fetchone()
                if row:
                    cursor.execute("UPDATE applications SET status = 'Interview' WHERE id = ?", (row["id"],))

            conn.commit()
            return (interview_id, True)

    def list_interviews(
        self,
        status: Optional[str] = None,
        start_date: Optional[Union[str, datetime, date]] = None,
        end_date: Optional[Union[str, datetime, date]] = None,
    ) -> List[Dict[str, Any]]:
        """Lists interviews ordered by date with optional date range filtering."""
        norm_start = parse_flexible_date(start_date) if start_date else None
        norm_end = parse_flexible_date(end_date) if end_date else None

        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM interviews WHERE 1=1"
            params: List[Any] = []
            if status:
                query += " AND LOWER(status) = LOWER(?)"
                params.append(status)
            if norm_start:
                query += " AND substr(interview_date, 1, 10) >= ?"
                params.append(norm_start)
            if norm_end:
                query += " AND substr(interview_date, 1, 10) <= ?"
                params.append(norm_end)
            query += " ORDER BY interview_date ASC"
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

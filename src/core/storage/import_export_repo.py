"""Data import and export repository for JobAgent.

Handles:
- Bulk import of applications and consolidated interviews from JSON summary files.
- Role extraction fallback and preservation of verified titles.
- Statutory compliance integrity (preserves UNKNOWN_ROLE rather than fabricating titles).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.role_extractor import extract_role_from_context
from src.core.storage.base import BaseStorage, UNKNOWN_ROLE

log = logging.getLogger(__name__)


class ImportExportRepo(BaseStorage):
    """Repository handling import and export operations."""

    def import_from_summary(
        self,
        summary_path: str,
        interviews_path: Optional[str] = None,
    ) -> Dict[str, int]:
        """Imports applications and interviews from applications_summary.json / interviews_consolidated.json."""
        s_path = Path(summary_path)
        if not s_path.exists():
            raise FileNotFoundError(f"Applications summary file not found: {summary_path}")

        with open(s_path, "r", encoding="utf-8") as f:
            summary_data = json.load(f)

        apps = summary_data.get("applications", [])
        apps_count = 0

        with self._get_connection() as conn:
            cursor = conn.cursor()
            for app in apps:
                company = (app.get("company") or "").strip()
                if not company or len(company) < 2:
                    continue

                existing_id = None
                existing_role = None
                cursor.execute("SELECT id, role FROM applications WHERE LOWER(company) = LOWER(?)", (company,))
                existing_row = cursor.fetchone()
                if existing_row:
                    existing_id = existing_row["id"]
                    existing_role = (existing_row["role"] or "").strip()

                role = (app.get("job_title") or "").strip()
                if not role or role in ["—", "-", "this", ""]:
                    emails = app.get("emails", [])
                    subj = emails[0].get("subject", "") if emails else ""
                    snippet = emails[0].get("snippet", "") if emails else ""
                    extracted = extract_role_from_context(subj, snippet)
                    if extracted:
                        role = extracted

                if not role:
                    if existing_id is not None and existing_role not in (None, "", UNKNOWN_ROLE):
                        # The application already has a real role; never clobber it
                        # with the unknown placeholder (data-integrity rule).
                        role = existing_role
                    else:
                        role = UNKNOWN_ROLE

                applied_date = app.get("application_date") or datetime.now(timezone.utc).isoformat()
                raw_status = (app.get("status") or "").lower()
                if "interview" in raw_status:
                    status = "Interview"
                elif "reject" in raw_status:
                    status = "Rejected"
                else:
                    status = "Applied"

                email_count = app.get("email_count", len(app.get("emails", [])))
                notes = f"Imported from summary ({email_count} emails linked)"

                if existing_id is not None:
                    cursor.execute(
                        """
                        UPDATE applications
                        SET role = ?, applied_date = ?, status = ?, source = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (role, applied_date, status, "Direct / ATS", notes, existing_id),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO applications (company, role, applied_date, status, source, notes, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """,
                        (company, role, applied_date, status, "Direct / ATS", notes),
                    )
                apps_count += 1
            conn.commit()

        # Import interviews if provided or auto-detected in same directory
        interviews_count = 0
        int_p = Path(interviews_path) if interviews_path else s_path.parent / "interviews_consolidated.json"
        if int_p.exists():
            with open(int_p, "r", encoding="utf-8") as f:
                int_data = json.load(f)

            int_list = int_data if isinstance(int_data, list) else int_data.get("interviews", [])
            for item in int_list:
                comp = item.get("company")
                if not comp:
                    continue
                role = (item.get("job_title") or "").strip()
                if not role or role in ["—", "-", "this", ""]:
                    # Never fabricate a role: leave the interview role unknown for
                    # human review instead of inventing one for the AfA records.
                    role = UNKNOWN_ROLE
                itype = item.get("interview_type") or "Interview"
                idate = item.get("latest_date") or item.get("first_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT id FROM applications WHERE LOWER(company) = LOWER(?)", (comp,))
                    r = cursor.fetchone()
                    app_id = r[0] if r else None

                # Call record_interview via unified instance
                getattr(self, "record_interview")(
                    company=comp,
                    interview_date=idate,
                    role=role,
                    application_id=app_id,
                    interview_type=itype,
                    status="Scheduled",
                    notes=f"Consolidated interview ({item.get('call_count', 1)} emails)",
                )
                interviews_count += 1

        return {
            "applications_imported": apps_count,
            "interviews_imported": interviews_count,
        }

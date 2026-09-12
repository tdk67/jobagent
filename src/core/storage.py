"""Local SQLite repository and data storage for JobAgent.

Ensures:
- 100% private local storage (zero cloud PII leakage).
- Atomic schema migrations and transactions.
- Unified querying across applications, email interactions, interviews, and QA memory.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from src.core.migrations import run_migrations
from src.core.normalizer import is_noise_company, normalize_company_name, normalize_role_title
from src.core.role_extractor import extract_role_from_context
from src.utils.date_utils import parse_flexible_date

log = logging.getLogger(__name__)

# Role used when no role can be parsed from the import data. Must NEVER be a
# fabricated real-sounding title: this value ends up in the statutory AfA
# Eigenbemühungsnachweis, where invented data would be a compliance problem.
UNKNOWN_ROLE = "Unbekannt (bitte prüfen)"


class JobAgentStorage:
    def __init__(self, db_path: str = "data/jobagent.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initializes database tables using the versioned migration framework."""
        run_migrations(self.db_path)

    def upsert_application(
        self,
        company: str,
        role: str,
        applied_date: Optional[str] = None,
        status: str = "Applied",
        source: str = "Direct",
        job_url: Optional[str] = None,
        location: Optional[str] = None,
        salary_info: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[int]:
        """Inserts or updates a job application with canonical company deduplication.
        Filters aggregator noise (LinkedIn, BambooHR) and merges duplicate legal forms (GmbH, AG).
        """
        if is_noise_company(company):
            log.debug("Filtered noise company entity: %r", company)
            return None

        canon_company = normalize_company_name(company) or company.strip()
        cleaned_role = normalize_role_title(role)
        canon_role = cleaned_role or role.strip()

        if not canon_company:
            return None

        now = datetime.now(timezone.utc).isoformat()
        app_date = applied_date or now

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. Exact canonical company match
            cursor.execute(
                "SELECT id, company, role, status, applied_date FROM applications WHERE LOWER(company) = LOWER(?)",
                (canon_company,),
            )
            rows = cursor.fetchall()

            target_row = None
            if rows:
                if cleaned_role:
                    # Look for exact or normalized role match
                    for r in rows:
                        ex_cleaned = normalize_role_title(r["role"])
                        if ex_cleaned and ex_cleaned.lower() == cleaned_role.lower():
                            target_row = r
                            break
                    # If no exact role match, look for an entry with an unparsed/placeholder role to upgrade
                    if target_row is None:
                        for r in rows:
                            if not normalize_role_title(r["role"]):
                                target_row = r
                                break
                else:
                    # Incoming role is placeholder/empty -> link to most recent application for this company
                    target_row = rows[0]

            if target_row:
                app_id = target_row["id"]
                existing_role = target_row["role"]
                existing_status = target_row["status"]
                existing_applied_date = target_row["applied_date"]

                # Upgrade role if existing is placeholder and new is concrete
                new_role = existing_role
                if (not normalize_role_title(existing_role)) and cleaned_role:
                    new_role = cleaned_role

                # Status progression: Interview > Rejected > Applied
                new_status = existing_status
                if status == "Interview":
                    new_status = "Interview"
                elif status == "Rejected" and existing_status != "Interview":
                    new_status = "Rejected"

                # Keep earliest valid applied_date
                earliest_date = existing_applied_date
                if applied_date and (not existing_applied_date or applied_date < existing_applied_date):
                    earliest_date = applied_date

                cursor.execute(
                    """
                    UPDATE applications 
                    SET company = ?, role = ?, status = ?, applied_date = ?,
                        source = COALESCE(?, source), job_url = COALESCE(?, job_url),
                        location = COALESCE(?, location), salary_info = COALESCE(?, salary_info),
                        notes = COALESCE(?, notes), updated_at = ?
                    WHERE id = ?
                    """,
                    (canon_company, new_role, new_status, earliest_date, source, job_url, location, salary_info, notes, now, app_id),
                )
                conn.commit()
                return app_id
            else:
                cursor.execute(
                    """
                    INSERT INTO applications (company, role, applied_date, status, source, job_url, location, salary_info, notes, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (canon_company, canon_role, app_date, status, source, job_url, location, salary_info, notes, now, now),
                )
                conn.commit()
                return cursor.lastrowid

    def deduplicate_applications(self) -> Dict[str, int]:
        """Cleans existing applications in the database by merging duplicate companies,
        preserving distinct roles at the same company, and purging aggregator noise.
        """
        from collections import defaultdict

        merged_count = 0
        deleted_noise_count = 0

        with self._get_connection() as conn:
            cursor = conn.cursor()
            apps = cursor.execute("SELECT * FROM applications").fetchall()

            # 1. Remove noise companies (e.g. 'h LinkedIn', 'notifications@app.bamboohr.com')
            for app in apps:
                if is_noise_company(app["company"]):
                    app_id = app["id"]
                    cursor.execute("UPDATE email_interactions SET application_id = NULL WHERE application_id = ?", (app_id,))
                    cursor.execute("UPDATE interviews SET application_id = NULL WHERE application_id = ?", (app_id,))
                    cursor.execute("DELETE FROM applications WHERE id = ?", (app_id,))
                    deleted_noise_count += 1

            # 2. Re-query surviving applications and group by company
            apps = cursor.execute("SELECT * FROM applications").fetchall()
            by_canon = defaultdict(list)
            for app in apps:
                canon = normalize_company_name(app["company"]) or app["company"].strip()
                by_canon[canon.lower()].append((canon, app))

            # 3. Sub-cluster by (company, concrete_role) to keep distinct positions separate
            clusters = []
            for canon_lower, group in by_canon.items():
                canon_name = group[0][0]
                by_role = defaultdict(list)
                placeholders = []
                for _, app in group:
                    r_clean = normalize_role_title(app["role"])
                    if r_clean:
                        by_role[r_clean.lower()].append(app)
                    else:
                        placeholders.append(app)

                if by_role:
                    role_keys = list(by_role.keys())
                    by_role[role_keys[0]].extend(placeholders)
                    for _, r_records in by_role.items():
                        clusters.append((canon_name, r_records))
                else:
                    clusters.append((canon_name, [g[1] for g in group]))

            # 4. Merge duplicate clusters
            for canon_name, records in clusters:
                if len(records) == 1:
                    app = records[0]
                    clean_role = normalize_role_title(app["role"]) or app["role"]
                    if app["company"] != canon_name or app["role"] != clean_role:
                        cursor.execute(
                            "UPDATE applications SET company = ?, role = ? WHERE id = ?",
                            (canon_name, clean_role, app["id"]),
                        )
                    continue

                def rank_record(r):
                    has_real_role = 1 if normalize_role_title(r["role"]) else 0
                    status_rank = 3 if r["status"] == "Interview" else (2 if r["status"] == "Rejected" else 1)
                    return (has_real_role, status_rank, -r["id"])

                records.sort(key=rank_record, reverse=True)
                primary = records[0]
                primary_id = primary["id"]

                best_role = normalize_role_title(primary["role"])
                if not best_role:
                    for r in records:
                        cand = normalize_role_title(r["role"])
                        if cand:
                            best_role = cand
                            break
                if not best_role:
                    best_role = primary["role"]

                best_status = primary["status"]
                if any(r["status"] == "Interview" for r in records):
                    best_status = "Interview"
                elif any(r["status"] == "Rejected" for r in records) and best_status != "Interview":
                    best_status = "Rejected"

                earliest_date = min([r["applied_date"] for r in records if r["applied_date"]] or [primary["applied_date"]])

                cursor.execute(
                    """
                    UPDATE applications 
                    SET company = ?, role = ?, status = ?, applied_date = ?
                    WHERE id = ?
                    """,
                    (canon_name, best_role, best_status, earliest_date, primary_id),
                )

                for secondary in records[1:]:
                    sec_id = secondary["id"]
                    cursor.execute("UPDATE email_interactions SET application_id = ? WHERE application_id = ?", (primary_id, sec_id))
                    cursor.execute("UPDATE interviews SET application_id = ? WHERE application_id = ?", (primary_id, sec_id))
                    cursor.execute("DELETE FROM applications WHERE id = ?", (sec_id,))
                    merged_count += 1

            conn.commit()

        return {"merged": merged_count, "noise_deleted": deleted_noise_count}

    def save_raw_email(
        self,
        entry_id: str,
        folder: str,
        sender_name: str,
        sender_email: str,
        subject: str,
        body: str,
        preview: str,
        received_time: str,
    ) -> bool:
        """Idempotently saves raw email into raw_emails table with ISO week tracking."""
        if not entry_id:
            return False

        iso_week = ""
        try:
            parsed_d = parse_flexible_date(received_time)
            if parsed_d:
                dt = datetime.strptime(parsed_d, "%Y-%m-%d")
                iso_week = f"{dt.year}-W{dt.isocalendar()[1]:02d}"
        except Exception:
            pass
        if not iso_week:
            iso_week = "Unknown"

        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO raw_emails (entry_id, folder, sender_name, sender_email, subject, body, preview, received_time, iso_week, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (entry_id, folder, sender_name, sender_email, subject, body, preview, received_time, iso_week, now),
            )
            conn.commit()
            return cursor.rowcount > 0

    def list_raw_emails(
        self,
        folder: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        iso_week: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Queries stored raw emails with optional date, folder, or ISO week filters."""
        query = "SELECT * FROM raw_emails WHERE 1=1"
        params: List[Any] = []
        if folder:
            query += " AND LOWER(folder) = LOWER(?)"
            params.append(folder)
        if iso_week:
            query += " AND iso_week = ?"
            params.append(iso_week)
        if start_date:
            s_iso = parse_flexible_date(start_date)
            if s_iso:
                query += " AND substr(received_time, 1, 10) >= ?"
                params.append(s_iso)
        if end_date:
            e_iso = parse_flexible_date(end_date)
            if e_iso:
                query += " AND substr(received_time, 1, 10) <= ?"
                params.append(e_iso)
        query += " ORDER BY received_time DESC"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

    def get_application_emails(self, application_id: int) -> List[Dict[str, Any]]:
        """Retrieves all email interactions linked to an application for traceability and auditing."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM email_interactions WHERE application_id = ? ORDER BY received_time ASC",
                (application_id,),
            )
            return [dict(r) for r in cursor.fetchall()]


    def get_application_by_company(self, company: str) -> Optional[Dict[str, Any]]:
        """Finds application by company name with canonical normalization."""
        canon = normalize_company_name(company) or company.strip()
        comp = canon.lower()
        raw_comp = company.strip().lower()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM applications WHERE LOWER(company) = ? OR LOWER(company) = ? ORDER BY applied_date DESC LIMIT 1",
                (comp, raw_comp),
            )
            row = cursor.fetchone()
            if row:
                return dict(row)

            cursor.execute(
                """
                SELECT * FROM applications 
                WHERE LOWER(company) LIKE ? 
                   OR LOWER(?) LIKE LOWER(company) || '%'
                   OR ? LIKE '%' || LOWER(company) || '%'
                ORDER BY applied_date DESC LIMIT 1
                """,
                (f"%{comp}%", raw_comp, raw_comp),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_applications(
        self,
        status: Optional[str] = None,
        start_date: Optional[Union[str, datetime, date]] = None,
        end_date: Optional[Union[str, datetime, date]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Lists all applications with optional status and date range filtering."""
        norm_start = parse_flexible_date(start_date) if start_date else None
        norm_end = parse_flexible_date(end_date) if end_date else None

        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM applications WHERE 1=1"
            params: List[Any] = []
            if status:
                query += " AND LOWER(status) = LOWER(?)"
                params.append(status)
            if norm_start:
                query += " AND substr(applied_date, 1, 10) >= ?"
                params.append(norm_start)
            if norm_end:
                query += " AND substr(applied_date, 1, 10) <= ?"
                params.append(norm_end)
            query += " ORDER BY applied_date DESC"
            if limit:
                query += " LIMIT ?"
                params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def update_application_status(self, app_id: int, status: str, notes: Optional[str] = None) -> None:
        """Updates status and notes for an application."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if notes:
                cursor.execute(
                    "UPDATE applications SET status = ?, notes = ?, updated_at = ? WHERE id = ?",
                    (status, notes, now, app_id),
                )
            else:
                cursor.execute(
                    "UPDATE applications SET status = ?, updated_at = ? WHERE id = ?",
                    (status, now, app_id),
                )
            conn.commit()

    def record_email_interaction(
        self,
        entry_id: str,
        category: str,
        sender_name: str,
        sender_email: str,
        subject: str,
        received_time: str,
        preview: str = "",
        application_id: Optional[int] = None,
        confidence_score: float = 1.0,
        action_taken: str = "",
    ) -> int:
        """Records an ingested email interaction, preventing duplicate entry_ids."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO email_interactions 
                (application_id, entry_id, sender_name, sender_email, subject, received_time, category, preview, confidence_score, action_taken)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entry_id) DO UPDATE SET 
                    application_id = COALESCE(excluded.application_id, email_interactions.application_id),
                    category = excluded.category,
                    action_taken = excluded.action_taken,
                    confidence_score = excluded.confidence_score
                """,
                (application_id, entry_id, sender_name, sender_email, subject, received_time, category, preview, confidence_score, action_taken),
            )
            conn.commit()
            return cursor.lastrowid

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
        Returns a tuple of (interview_id, created) to prevent duplicate alerts on re-ingest cycles (H5).
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

    def get_statistics(
        self,
        start_date: Optional[Union[str, datetime, date]] = None,
        end_date: Optional[Union[str, datetime, date]] = None,
    ) -> Dict[str, Any]:
        """Calculates funnel KPIs and weekly aggregation with optional date filtering."""
        norm_start = parse_flexible_date(start_date) if start_date else None
        norm_end = parse_flexible_date(end_date) if end_date else None

        where_clause = " WHERE 1=1"
        params: List[Any] = []
        if norm_start:
            where_clause += " AND substr(applied_date, 1, 10) >= ?"
            params.append(norm_start)
        if norm_end:
            where_clause += " AND substr(applied_date, 1, 10) <= ?"
            params.append(norm_end)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) as total FROM applications{where_clause}", params)
            total_apps = cursor.fetchone()["total"]

            cursor.execute(
                f"SELECT COUNT(*) as count FROM applications{where_clause} AND LOWER(status) = 'interview'",
                params,
            )
            total_interviews = cursor.fetchone()["count"]

            cursor.execute(
                f"SELECT COUNT(*) as count FROM applications{where_clause} AND LOWER(status) = 'rejected'",
                params,
            )
            total_rejections = cursor.fetchone()["count"]

            cursor.execute(
                f"SELECT COUNT(*) as count FROM applications{where_clause} AND LOWER(status) = 'applied'",
                params,
            )
            total_pending = cursor.fetchone()["count"]

            response_rate = round((total_interviews / total_apps * 100), 1) if total_apps > 0 else 0.0
            rejection_rate = round((total_rejections / total_apps * 100), 1) if total_apps > 0 else 0.0

            cursor.execute(f"""
                SELECT strftime('%Y-W%W', applied_date) as week, COUNT(*) as count
                FROM applications{where_clause}
                GROUP BY week
                ORDER BY week ASC
            """, params)
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
        apps = self.list_applications(start_date=start_date, end_date=end_date)
        interviews = self.list_interviews(start_date=start_date, end_date=end_date)

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
                "SELECT application_id, entry_id, category, subject, received_time, sender_name "
                "FROM email_interactions WHERE application_id IS NOT NULL ORDER BY received_time ASC"
            )
            for r in cursor.fetchall():
                aid = r["application_id"]
                app_emails_map.setdefault(aid, []).append(dict(r))

        # Format applications for German AfA statutory format and dashboards
        formatted_apps = []
        for idx, app in enumerate(apps, 1):
            applied_dt_str = app.get("applied_date", "")
            try:
                dt = datetime.fromisoformat(applied_dt_str.replace("Z", "+00:00"))
                display_date = dt.strftime("%d.%m.%Y")
            except Exception as e:
                log.debug("Date parse fallback for %s: %s", applied_dt_str, e)
                display_date = applied_dt_str[:10]

            app_id = app.get("id")
            linked = app_emails_map.get(app_id, [])
            entry_ids = [m["entry_id"] for m in linked if m.get("entry_id")]

            formatted_apps.append({
                "index": idx,
                "id": app_id,
                "company": app.get("company", "—"),
                "role": app.get("role", "—"),
                "applied_date": display_date,
                "status": app.get("status", "Applied"),
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

    # =========================================================================
    # Continuous Learning & QA Memory Repository
    # =========================================================================

    @staticmethod
    def normalize_question(text: str) -> str:
        """Normalizes question text for consistent canonical lookup."""
        if not text:
            return ""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def save_qa_answer(
        self,
        question_text: Optional[str] = None,
        answer: str = "",
        category: str = "general",
        verified: int = 1,
        provenance: str = "user_verified",
        question: Optional[str] = None,
    ) -> None:
        """Saves or updates a question-answer pair into persistent QA memory with provenance tracking (C3)."""
        raw_q = question_text or question or ""
        norm_key = self.normalize_question(raw_q)
        if not norm_key or len(norm_key) < 3:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO qa_memory (question_key, question_text, answer, category, verified, provenance, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(question_key) DO UPDATE SET
                    question_text = excluded.question_text,
                    answer = excluded.answer,
                    category = excluded.category,
                    verified = excluded.verified,
                    provenance = excluded.provenance,
                    updated_at = excluded.updated_at
                """,
                (norm_key, raw_q.strip(), str(answer).strip(), category, verified, provenance, now),
            )
            conn.commit()

    def get_qa_answer(self, question_text: str, verified_only: bool = True) -> Optional[str]:
        """Looks up a question in persistent QA memory by exact canonical key or significant phrase/token overlap (C4).
        
        Args:
            question_text: Natural language question text.
            verified_only: When True (default), only return user-verified answers (verified=1).
                           Prevents unverified LLM suggestions from being treated as authoritative (C3).
        """
        norm_key = self.normalize_question(question_text)
        # Protect against garbage 1-2 char searches (e.g. 'a', 'e', 'sal')
        if not norm_key or len(norm_key) < 3:
            return None

        where_cond = "WHERE verified = 1" if verified_only else ""
        where_key_cond = "WHERE question_key = ?" + (" AND verified = 1" if verified_only else "")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. Exact canonical match
            cursor.execute(
                f"SELECT answer FROM qa_memory {where_key_cond}",
                (norm_key,),
            )
            row = cursor.fetchone()
            if row:
                return row["answer"]

            # 2. Phrase and token-overlap match (eliminates accidental substring hits like 'a' in 'salary')
            cursor.execute(f"SELECT question_key, answer FROM qa_memory {where_cond}")
            all_entries = cursor.fetchall()

            query_tokens = set(norm_key.split())
            stop_words = {
                "in", "for", "a", "an", "the", "der", "die", "das", "und", "oder", "ist", "sind",
                "do", "you", "your", "have", "please", "bitte", "geben", "sie", "an", "ihre",
                "deine", "mit", "what", "which", "where", "how", "many", "is", "are", "my", "of",
            }
            significant_query = {t for t in query_tokens if len(t) >= 3 and t not in stop_words}
            padded_query = f" {norm_key} "

            best_match = None
            best_score = 0.0

            for r in all_entries:
                key = r["question_key"]
                if not key or len(key) < 3:
                    continue

                padded_key = f" {key} "

                # Whole phrase match with word boundaries in either direction
                # (e.g. "expected salary" inside "what is your expected salary")
                # Enforces that query contains at least one significant non-stop word
                if (padded_query in padded_key or padded_key in padded_query) and significant_query:
                    return r["answer"]

                key_tokens = set(key.split())
                significant_key = {t for t in key_tokens if len(t) >= 3 and t not in stop_words}
                if not significant_key or not significant_query:
                    continue

                overlap = len(significant_query & significant_key)
                # Score against smaller set to handle concise queries matching longer questions
                min_len = min(len(significant_key), len(significant_query))
                score = overlap / min_len
                if score >= 0.7 and score > best_score:
                    best_score = score
                    best_match = r["answer"]

            if best_match:
                return best_match

        return None

    def list_qa_memory(self) -> List[Dict[str, Any]]:
        """Returns all stored QA memory entries."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM qa_memory ORDER BY updated_at DESC")
            return [dict(r) for r in cursor.fetchall()]

    def seed_qa_from_profile(self, profile: Any) -> None:
        """Seeds QA memory from CandidateProfile common_answers and skills."""
        if not profile:
            return

        common_answers = getattr(profile, "common_answers", {}) or {}
        for q, a in common_answers.items():
            self.save_qa_answer(q, str(a), category="profile_common")

        # Technical skills years
        tech = getattr(profile, "technical_skills", None)
        years = getattr(tech, "yearsExperience", {}) if tech else {}
        SKILL_TEMPLATES = [
            ("How many years of experience do you have with {skill}?", "{yr} years"),
            ("Wie viele Jahre Erfahrung haben Sie mit {skill}?", "{yr} Jahre"),
        ]
        for skill, yr in years.items():
            for q_tmpl, a_tmpl in SKILL_TEMPLATES:
                self.save_qa_answer(
                    q_tmpl.format(skill=skill),
                    a_tmpl.format(yr=yr),
                    category="skill_experience",
                )

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

                self.record_interview(
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



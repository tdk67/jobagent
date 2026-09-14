"""Email interaction and raw email repository for JobAgent.

Handles:
- Ingestion and querying of raw emails with ISO calendar week tracking.
- Idempotent recording of email interactions linked to job applications.
- Traceability and audit trail for German statutory reporting.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.storage.base import BaseStorage
from src.utils.date_utils import parse_flexible_date

log = logging.getLogger(__name__)


class EmailRepo(BaseStorage):
    """Repository handling raw emails and triage interactions."""

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
        reasoning: Optional[str] = None,
        intent: Optional[str] = None,
    ) -> int:
        """Records an ingested email interaction, preventing duplicate entry_ids."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO email_interactions 
                (application_id, entry_id, sender_name, sender_email, subject, received_time, category, preview, confidence_score, action_taken, reasoning, intent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entry_id) DO UPDATE SET 
                    application_id = COALESCE(excluded.application_id, email_interactions.application_id),
                    category = excluded.category,
                    action_taken = excluded.action_taken,
                    confidence_score = excluded.confidence_score,
                    reasoning = COALESCE(excluded.reasoning, email_interactions.reasoning),
                    intent = COALESCE(excluded.intent, email_interactions.intent)
                """,
                (application_id, entry_id, sender_name, sender_email, subject, received_time, category, preview, confidence_score, action_taken, reasoning, intent),
            )
            conn.commit()
            return cursor.lastrowid

    def get_raw_email(self, entry_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves raw email by entry_id including body, preview, sender, and headers."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM raw_emails WHERE entry_id = ?",
                (entry_id,),
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            # Fallback to email_interactions if not cached in raw_emails
            cursor.execute(
                "SELECT entry_id, sender_name, sender_email, subject, received_time, preview, category FROM email_interactions WHERE entry_id = ?",
                (entry_id,),
            )
            row2 = cursor.fetchone()
            return dict(row2) if row2 else None

    def reconcile_unlinked(self) -> Dict[str, Any]:
        """Reconciles unlinked email interactions and enriches applications.
        
        Uses algorithmic channel extraction and location deduction, completely
        eliminating hardcoded platform lists and raw SQLite queries in service layers.
        """
        from src.core.channel_extractor import extract_channel, extract_channel_from_domain, CONSUMER_DOMAINS
        from src.core.location_extractor import extract_location
        from src.core.normalizer import normalize_company_name

        with self._get_connection() as conn:
            cursor = conn.cursor()

            from collections import defaultdict
            # 1. Fetch all applications
            cursor.execute("SELECT id, company, role, location, source, applied_date FROM applications")
            apps = cursor.fetchall()

            apps_by_comp: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for a in apps:
                comp = (a["company"] or "").strip()
                if comp and len(comp) >= 2:
                    norm = normalize_company_name(comp).lower()
                    apps_by_comp[norm].append(dict(a))
                    if comp.lower() != norm:
                        apps_by_comp[comp.lower()].append(dict(a))

            def _find_best_app(app_list: List[Dict[str, Any]], email_dt_str: Optional[str]) -> Optional[int]:
                if not app_list:
                    return None
                if len(app_list) == 1:
                    return app_list[0]["id"]
                from src.utils.date_utils import parse_flexible_date
                parsed_email = parse_flexible_date(email_dt_str) if email_dt_str else None
                if not parsed_email:
                    return app_list[-1]["id"]
                best_app = app_list[0]
                best_diff = float("inf")
                for candidate in app_list:
                    c_date = parse_flexible_date(candidate.get("applied_date"))
                    if c_date and c_date <= parsed_email:
                        try:
                            d1 = datetime.strptime(c_date, "%Y-%m-%d")
                            d2 = datetime.strptime(parsed_email, "%Y-%m-%d")
                            diff = (d2 - d1).days
                            if 0 <= diff < best_diff:
                                best_diff = diff
                                best_app = candidate
                        except Exception:
                            pass
                return best_app["id"]

            # 2. Fetch unlinked email interactions (strictly excluding noise/other)
            cursor.execute("""
            SELECT id, entry_id, sender_name, sender_email, subject, preview, received_time, category 
            FROM email_interactions 
            WHERE application_id IS NULL
              AND category NOT IN ('noise', 'other')
            """)
            unlinked = cursor.fetchall()
            linked_count = 0

            for email_row in unlinked:
                eid = email_row["id"]
                s_name = (email_row["sender_name"] or "").strip()
                s_email = (email_row["sender_email"] or "").strip()
                subj = (email_row["subject"] or "").strip()
                recv_time = email_row["received_time"] or ""

                matched_app_id = None

                # Strategy A: Check sender_name direct match
                if s_name:
                    norm_name = normalize_company_name(s_name).lower()
                    if norm_name in apps_by_comp:
                        matched_app_id = _find_best_app(apps_by_comp[norm_name], recv_time)
                    elif s_name.lower() in apps_by_comp:
                        matched_app_id = _find_best_app(apps_by_comp[s_name.lower()], recv_time)

                # Strategy B: Check subject tokens against application company names
                if not matched_app_id:
                    subj_lower = subj.lower()
                    for norm_comp, app_candidates in apps_by_comp.items():
                        if len(norm_comp) >= 4 and norm_comp in subj_lower:
                            matched_app_id = _find_best_app(app_candidates, recv_time)
                            break

                # Strategy C: Check sender email domain against application company names
                if not matched_app_id and "@" in s_email:
                    email_domain = s_email.split("@")[-1].lower().strip()
                    if email_domain not in CONSUMER_DOMAINS:
                        domain_prefix = email_domain.split(".")[0]
                        for norm_comp, app_candidates in apps_by_comp.items():
                            if len(domain_prefix) >= 3 and (domain_prefix in norm_comp or norm_comp in domain_prefix):
                                matched_app_id = _find_best_app(app_candidates, recv_time)
                                break

                if matched_app_id:
                    cursor.execute("UPDATE email_interactions SET application_id = ? WHERE id = ?", (matched_app_id, eid))
                    linked_count += 1

            conn.commit()

            # 3. Enrich locations and channels across applications
            enriched_locations = 0
            enriched_channels = 0

            cursor.execute("SELECT id, company, role, location, source FROM applications")
            refreshed_apps = cursor.fetchall()

            for a in refreshed_apps:
                app_id = a["id"]
                current_loc = (a["location"] or "").strip()
                current_source = (a["source"] or "").strip()

                cursor.execute("""
                SELECT e.subject, e.sender_email, e.sender_name, e.preview, r.body
                FROM email_interactions e
                LEFT JOIN raw_emails r ON e.entry_id = r.entry_id
                WHERE e.application_id = ?
                """, (app_id,))
                email_evidence = cursor.fetchall()

                text_evidence = [a["role"], a["company"]]
                email_sources: List[str] = []
                sender_names: List[str] = []

                for ev in email_evidence:
                    text_evidence.append(ev["subject"])
                    text_evidence.append(ev["preview"])
                    if ev["body"]:
                        text_evidence.append(ev["body"])
                    if ev["sender_email"]:
                        email_sources.append(ev["sender_email"])
                    if ev["sender_name"]:
                        sender_names.append(ev["sender_name"])

                # Deduce Location
                new_loc = current_loc
                if not current_loc or current_loc == "—":
                    deduced_loc = extract_location(*text_evidence)
                    if deduced_loc:
                        new_loc = deduced_loc
                        enriched_locations += 1

                # Deduce Channel
                new_channel = current_source
                if current_source in ("Direct / ATS", "Direct", "Email Ingestion", ""):
                    primary_sender = email_sources[0] if email_sources else None
                    primary_name = sender_names[0] if sender_names else None
                    deduced_channel = extract_channel(
                        sender_email=primary_sender,
                        sender_name=primary_name,
                        existing_source=current_source,
                    )
                    if deduced_channel and deduced_channel != current_source:
                        new_channel = deduced_channel
                        enriched_channels += 1

                if new_loc != current_loc or new_channel != current_source:
                    cursor.execute(
                        "UPDATE applications SET location = ?, source = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (new_loc or "—", new_channel, app_id),
                    )

            conn.commit()

            return {
                "emails_reconciled": linked_count,
                "locations_enriched": enriched_locations,
                "channels_enriched": enriched_channels,
            }

    def create_pending_approval(
        self,
        question: str,
        context: str = "",
        urgency: str = "normal",
    ) -> int:
        """Creates a pending approval request for human confirmation."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO pending_approvals (question, context, urgency, status, created_at)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (question, context, urgency, now),
            )
            conn.commit()
            return cursor.lastrowid

    def list_pending_approvals(self, status: str = "pending") -> List[Dict[str, Any]]:
        """Lists approval requests filtered by status."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM pending_approvals WHERE status = ? ORDER BY created_at DESC",
                (status,),
            )
            return [dict(r) for r in cursor.fetchall()]

    def resolve_pending_approval(self, approval_id: int, response: str, approved: bool) -> bool:
        """Resolves an approval request."""
        now = datetime.now(timezone.utc).isoformat()
        new_status = "approved" if approved else "rejected"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE pending_approvals SET status = ?, response = ?, resolved_at = ? WHERE id = ?",
                (new_status, response, now, approval_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def record_agent_cycle(
        self,
        cycle_id: str,
        status: str,
        triage_result: Optional[Dict[str, Any]] = None,
        reports_result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Records cycle execution state to SQLite for auditability and recovery."""
        import json
        now = datetime.now(timezone.utc).isoformat()
        t_json = json.dumps(triage_result) if triage_result else None
        r_json = json.dumps(reports_result) if reports_result else None
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO agent_cycles (id, started_at, status, triage_result, reports_result, error)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    triage_result = COALESCE(excluded.triage_result, agent_cycles.triage_result),
                    reports_result = COALESCE(excluded.reports_result, agent_cycles.reports_result),
                    error = COALESCE(excluded.error, agent_cycles.error)
                """,
                (cycle_id, now, status, t_json, r_json, error),
            )
            conn.commit()

"""Job application repository for JobAgent.

Handles:
- CRUD operations on applications table.
- Normalization and noise filtering (LinkedIn, BambooHR, legal form stripping).
- Canonical deduplication and sub-clustering by role.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Union

from src.core.normalizer import is_noise_company, normalize_company_name, normalize_role_title
from src.core.storage.base import BaseStorage
from src.utils.date_utils import parse_flexible_date

log = logging.getLogger(__name__)


def _group_records_by_cycle(records: List[Any], cycle_threshold_days: int = 14) -> List[List[Any]]:
    """Groups applications into distinct cycles if applied_dates differ by more than threshold."""
    if not records:
        return []
    def _parse_dt(r: Any) -> datetime:
        d = r["applied_date"] if isinstance(r, dict) or hasattr(r, "__getitem__") else getattr(r, "applied_date", None)
        if not d or str(d) == "—":
            return datetime.min
        try:
            return datetime.fromisoformat(str(d)[:19].replace("Z", "+00:00"))
        except Exception:
            return datetime.min

    sorted_records = sorted(records, key=_parse_dt)
    cycles: List[List[Any]] = []
    for rec in sorted_records:
        rec_dt = _parse_dt(rec)
        placed = False
        for cycle in cycles:
            cycle_dt = _parse_dt(cycle[0])
            if cycle_dt == datetime.min or rec_dt == datetime.min:
                cycle.append(rec)
                placed = True
                break
            if abs((rec_dt - cycle_dt).total_seconds()) <= cycle_threshold_days * 86400:
                cycle.append(rec)
                placed = True
                break
        if not placed:
            cycles.append([rec])
    return cycles


class ApplicationRepo(BaseStorage):
    """Repository handling job applications, company deduplication, and status transitions."""

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
        job_description_md: Optional[str] = None,
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
                def _parse_app_dt(d_str: Any) -> Optional[datetime]:
                    if not d_str or str(d_str) == "—":
                        return None
                    try:
                        return datetime.fromisoformat(str(d_str)[:19].replace("Z", "+00:00"))
                    except Exception:
                        return None

                incoming_dt = _parse_app_dt(app_date)

                if cleaned_role:
                    # Look for exact or normalized role match
                    for r in rows:
                        ex_cleaned = normalize_role_title(r["role"])
                        if ex_cleaned and ex_cleaned.lower() == cleaned_role.lower():
                            r_dt = _parse_app_dt(r["applied_date"])
                            if r["status"] == "Rejected" and status in ("Applied", "Saved") and incoming_dt and r_dt:
                                if (incoming_dt - r_dt).total_seconds() > 7 * 86400:
                                    continue  # Skip closed cycle; create fresh application
                            target_row = r
                            break
                    # If no exact role match, look for an entry with an unparsed/placeholder role to upgrade
                    if target_row is None:
                        for r in rows:
                            if not normalize_role_title(r["role"]):
                                if r["status"] == "Rejected" and status in ("Applied", "Saved"):
                                    continue
                                target_row = r
                                break
                else:
                    # Incoming role is placeholder/empty -> link to active (non-rejected) application, or within same cycle
                    active_candidates = [
                        r for r in rows
                        if r["status"] != "Rejected" or (
                            incoming_dt and _parse_app_dt(r["applied_date"]) and
                            abs((incoming_dt - _parse_app_dt(r["applied_date"])).total_seconds()) <= 7 * 86400
                        )
                    ]
                    if active_candidates:
                        target_row = active_candidates[0]
                    else:
                        target_row = None

            if target_row:
                app_id = target_row["id"]
                existing_role = target_row["role"]
                existing_status = target_row["status"]
                existing_applied_date = target_row["applied_date"]

                # Upgrade role if existing is placeholder and new is concrete
                new_role = existing_role
                if (not normalize_role_title(existing_role)) and cleaned_role:
                    new_role = cleaned_role

                # Status progression: Interview > Rejected > Applied > Saved
                new_status = existing_status
                if status == "Interview":
                    new_status = "Interview"
                elif status == "Rejected" and existing_status != "Interview":
                    new_status = "Rejected"
                elif status == "Applied" and existing_status == "Saved":
                    new_status = "Applied"
                elif status == "Saved" and not existing_status:
                    new_status = "Saved"

                # Keep earliest valid applied_date
                earliest_date = existing_applied_date
                if applied_date and (not existing_applied_date or applied_date < existing_applied_date):
                    earliest_date = applied_date

                cursor.execute(
                    """
                    UPDATE applications 
                    SET company = ?, role = ?, status = ?, applied_date = ?,
                        source = COALESCE(?, source), job_url = COALESCE(?, job_url),
                        location = CASE WHEN ? IS NOT NULL AND ? != '—' AND ? != '' THEN ? ELSE location END,
                        salary_info = COALESCE(?, salary_info),
                        notes = COALESCE(?, notes),
                        job_description_md = COALESCE(?, job_description_md),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (canon_company, new_role, new_status, earliest_date, source, job_url, location, location, location, location, salary_info, notes, job_description_md, now, app_id),
                )
                conn.commit()
                return app_id
            else:
                cursor.execute(
                    """
                    INSERT INTO applications (company, role, applied_date, status, source, job_url, location, salary_info, notes, job_description_md, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (canon_company, canon_role, app_date, status, source, job_url, location, salary_info, notes, job_description_md, now, now),
                )
                conn.commit()
                return cursor.lastrowid

    def deduplicate_applications(self) -> Dict[str, int]:
        """Cleans existing applications in the database by merging duplicate companies,
        preserving distinct roles at the same company, and purging aggregator noise.
        """
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
                        # Sub-cluster records into distinct application cycles if dates differ by > 14 days
                        for cycle_records in _group_records_by_cycle(r_records):
                            clusters.append((canon_name, cycle_records))
                else:
                    for cycle_records in _group_records_by_cycle([g[1] for g in group]):
                        clusters.append((canon_name, cycle_records))

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

                def rank_record(r: sqlite3.Row) -> tuple[int, int, int]:
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

    def get_application_by_company(
        self,
        company: str,
        role: Optional[str] = None,
        date: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Finds best-matching application by company name, disambiguating by role, date, and lifecycle category."""
        canon = normalize_company_name(company) or company.strip()
        comp = canon.lower()
        raw_comp = company.strip().lower()
        cleaned_role = normalize_role_title(role) if role else None

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM applications WHERE LOWER(company) = ? OR LOWER(company) = ? ORDER BY applied_date DESC",
                (comp, raw_comp),
            )
            rows = [dict(r) for r in cursor.fetchall()]

            if not rows:
                cursor.execute(
                    """
                    SELECT * FROM applications 
                    WHERE LOWER(company) LIKE ? 
                       OR LOWER(?) LIKE LOWER(company) || '%'
                       OR ? LIKE '%' || LOWER(company) || '%'
                    ORDER BY applied_date DESC
                    """,
                    (f"%{comp}%", raw_comp, raw_comp),
                )
                rows = [dict(r) for r in cursor.fetchall()]

            if not rows:
                return None

            def _parse_dt(d_str: Any) -> Optional[datetime]:
                if not d_str or str(d_str) == "—":
                    return None
                try:
                    return datetime.fromisoformat(str(d_str)[:19].replace("Z", "+00:00"))
                except Exception:
                    return None

            target_dt = _parse_dt(date)

            # Lifecycle Strategy: If incoming email is an application confirmation (submitting application)
            if category == "application_confirmation":
                # A rejected application is terminal/closed. A new confirmation belongs to a new cycle!
                active_rows = [r for r in rows if r.get("status") != "Rejected"]
                if target_dt:
                    cycle_rows = []
                    for r in active_rows:
                        app_dt = _parse_dt(r.get("applied_date"))
                        if app_dt and abs((target_dt - app_dt).total_seconds()) <= 14 * 86400:
                            cycle_rows.append(r)
                    active_rows = cycle_rows
                if not active_rows:
                    return None
                rows = active_rows

            # Disambiguation Strategy 1: Match by role title
            matching_role_rows = []
            if cleaned_role:
                for r in rows:
                    ex_role = normalize_role_title(r.get("role"))
                    if ex_role and ex_role.lower() == cleaned_role.lower():
                        matching_role_rows.append(r)

                if not matching_role_rows:
                    # Token-based role matching (e.g. "AI-Engineer" in "Software-Entwickler:In / AI-Engineer")
                    role_tokens = [t for t in re.split(r"[^\w]", cleaned_role.lower()) if len(t) >= 4]
                    if role_tokens:
                        for r in rows:
                            ex_role = (r.get("role") or "").lower()
                            if any(tok in ex_role for tok in role_tokens):
                                matching_role_rows.append(r)

            if category == "application_confirmation":
                if cleaned_role:
                    # If concrete role was given for confirmation, it MUST match the role of the existing application.
                    # Never merge a confirmation for Role B into an existing application for Role A!
                    if not matching_role_rows:
                        return None
                    candidate_pool = matching_role_rows
                else:
                    # Generic / unknown confirmation role: only match active placeholder application in same cycle
                    placeholder_rows = [r for r in rows if not normalize_role_title(r.get("role"))]
                    if placeholder_rows:
                        candidate_pool = placeholder_rows
                    elif rows:
                        candidate_pool = rows
                    else:
                        return None
            else:
                candidate_pool = matching_role_rows if matching_role_rows else rows

            # Disambiguation Strategy 2: Date proximity and lifecycle sequencing
            if target_dt and len(candidate_pool) > 1:
                # If it's a status update (rejection or interview), prefer the application applied before or closest to target_dt
                preceding = []
                following = []
                for r in candidate_pool:
                    r_dt = _parse_dt(r.get("applied_date"))
                    if r_dt:
                        diff = (target_dt - r_dt).total_seconds()
                        if diff >= 0:
                            # Prioritize active applications over rejected ones for incoming events
                            active_penalty = 0 if r.get("status") != "Rejected" else 10000000
                            preceding.append((active_penalty, diff, r))
                        else:
                            following.append((abs(diff), r))
                if preceding:
                    preceding.sort(key=lambda x: (x[0], x[1]))
                    return preceding[0][2]
                if following:
                    following.sort(key=lambda x: x[0])
                    return following[0][1]

            return candidate_pool[0]

    def split_multi_cycle_applications(self) -> Dict[str, int]:
        """Inspects applications and splits any record into distinct application lifecycles when:
        1. A rejection is followed by a subsequent application confirmation at a later date, OR
        2. Multiple application confirmations exist for different roles or across distinct dates (>24h).
        """
        from src.tools.role_extractor import extract_role_from_context
        from src.core.location_extractor import extract_location

        def _parse_dt(d_str: Any) -> Optional[datetime]:
            if not d_str:
                return None
            try:
                return datetime.fromisoformat(str(d_str)[:19].replace("Z", "+00:00"))
            except Exception:
                return None

        splits_created = 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            apps = cursor.execute("SELECT * FROM applications").fetchall()

            for app in apps:
                app_id = app["id"]
                company = app["company"]

                cursor.execute(
                    """
                    SELECT e.*, COALESCE(r.body, e.preview) AS email_body
                    FROM email_interactions e
                    LEFT JOIN raw_emails r ON e.entry_id = r.entry_id
                    WHERE e.application_id = ?
                    ORDER BY e.received_time ASC
                    """,
                    (app_id,),
                )
                interactions = [dict(r) for r in cursor.fetchall()]
                if len(interactions) < 2:
                    continue

                # Enrich interactions with extracted role and datetime
                enriched = []
                for item in interactions:
                    body = item.get("email_body") or item.get("preview") or ""
                    cand_role = extract_role_from_context(
                        item.get("subject") or "", body[:4000], use_llm=False
                    )
                    norm_r = normalize_role_title(cand_role) if cand_role else None
                    dt = _parse_dt(item.get("received_time"))
                    enriched.append({
                        "item": item,
                        "role": norm_r,
                        "dt": dt,
                        "cat": item.get("category"),
                        "raw_body": body,
                    })

                clusters = [[enriched[0]]]
                for curr in enriched[1:]:
                    last_cluster = clusters[-1]
                    prev = last_cluster[-1]

                    had_rejection = any(x["cat"] == "rejection" for x in last_cluster)
                    is_conf = curr["cat"] == "application_confirmation"

                    time_gap_hours = (
                        (curr["dt"] - prev["dt"]).total_seconds() / 3600.0
                        if (curr["dt"] and prev["dt"])
                        else 0
                    )

                    # Split condition 1: Post-rejection new application cycle
                    if had_rejection and is_conf and time_gap_hours > 0:
                        clusters.append([curr])
                        continue

                    # Split condition 2: Multi-application / portal submissions without rejection
                    if is_conf:
                        if time_gap_hours > 36 or (
                            time_gap_hours > 12
                            and curr["role"]
                            and any(x["role"] and x["role"] != curr["role"] for x in last_cluster)
                        ):
                            clusters.append([curr])
                            continue

                    last_cluster.append(curr)

                if len(clusters) <= 1:
                    continue

                now = datetime.now(timezone.utc).isoformat()

                # Cluster 0 remains with original app_id
                c0 = clusters[0]
                c0_roles = [x["role"] for x in c0 if x["role"]]
                c0_role = c0_roles[0] if c0_roles else app["role"]
                c0_cats = [x["cat"] for x in c0]
                if "rejection" in c0_cats:
                    c0_status = "Rejected"
                elif "interview_invitation" in c0_cats:
                    c0_status = "Interview"
                else:
                    c0_status = "Applied"

                cursor.execute(
                    "UPDATE applications SET role = ?, status = ?, updated_at = ? WHERE id = ?",
                    (c0_role, c0_status, now, app_id),
                )

                # Clusters 1..N become new application records
                for c in clusters[1:]:
                    c_items = [x["item"] for x in c]
                    c_roles = [x["role"] for x in c if x["role"]]
                    c_role = c_roles[0] if c_roles else app["role"]
                    c_dt = c_items[0].get("received_time") or now
                    c_cats = [x["cat"] for x in c]

                    if "rejection" in c_cats:
                        c_status = "Rejected"
                    elif "interview_invitation" in c_cats:
                        c_status = "Interview"
                    else:
                        c_status = "Applied"

                    # Location detection
                    c_loc = app["location"]
                    for x in c:
                        cand_loc = extract_location(
                            x["item"].get("subject") or "", x["raw_body"] or "", c_role
                        )
                        if cand_loc and cand_loc != "—":
                            c_loc = cand_loc
                            break

                    cursor.execute(
                        """
                        INSERT INTO applications (company, role, applied_date, status, source, location, notes, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            company,
                            c_role,
                            c_dt,
                            c_status,
                            app["source"],
                            c_loc,
                            "Split from multi-application submissions",
                            now,
                            now,
                        ),
                    )
                    new_app_id = cursor.lastrowid

                    c_ids = [item["id"] for item in c_items]
                    placeholders = ",".join("?" for _ in c_ids)
                    cursor.execute(
                        f"UPDATE email_interactions SET application_id = ? WHERE id IN ({placeholders})",
                        [new_app_id] + c_ids,
                    )
                    splits_created += 1

            conn.commit()

        return {"splits_created": splits_created}


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
            query += " ORDER BY COALESCE(applied_date, created_at) DESC"
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

    def sync_unapplied_archive_statuses(self) -> int:
        """Enforces mathematical status invariants across the database:
        - An application can ONLY be 'Interview' if it has a linked 'interview_invitation' email.
        - An application can ONLY be 'Rejected' if it has a linked 'rejection' email.
        - An application with 0 emails is strictly 'Saved'.
        - Applications with genuine rejection emails are promoted to 'Rejected' (unless Interview).
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. Reset 'Interview' status for any application with NO interview invitation email OR with manual/phone rejection
            cursor.execute(
                """
                UPDATE applications
                SET status = CASE
                    WHEN notes LIKE '%phone%' OR notes LIKE '%manual%' THEN 'Rejected'
                    WHEN id IN (SELECT DISTINCT application_id FROM email_interactions WHERE category = 'rejection' AND application_id IS NOT NULL) THEN 'Rejected'
                    WHEN id IN (SELECT DISTINCT application_id FROM email_interactions WHERE application_id IS NOT NULL) THEN 'Applied'
                    ELSE 'Saved'
                END,
                updated_at = CURRENT_TIMESTAMP
                WHERE status = 'Interview'
                  AND (
                      id NOT IN (
                          SELECT DISTINCT application_id FROM email_interactions WHERE category = 'interview_invitation' AND application_id IS NOT NULL
                      )
                      OR notes LIKE '%phone%' OR notes LIKE '%manual%'
                  )
                """
            )
            interview_reset = cursor.rowcount

            # 2. Reset 'Rejected' status for any application with NO rejection email (unless recorded as phone/manual rejection)
            cursor.execute(
                """
                UPDATE applications
                SET status = CASE
                    WHEN id IN (SELECT DISTINCT application_id FROM email_interactions WHERE category = 'interview_invitation' AND application_id IS NOT NULL) THEN 'Interview'
                    WHEN id IN (SELECT DISTINCT application_id FROM email_interactions WHERE application_id IS NOT NULL) THEN 'Applied'
                    ELSE 'Saved'
                END,
                notes = CASE
                    WHEN notes LIKE 'Rejection email%' THEN NULL
                    ELSE notes
                END,
                updated_at = CURRENT_TIMESTAMP
                WHERE status = 'Rejected'
                  AND (notes IS NULL OR (notes NOT LIKE '%phone%' AND notes NOT LIKE '%manual%'))
                  AND id NOT IN (
                      SELECT DISTINCT application_id FROM email_interactions WHERE category = 'rejection' AND application_id IS NOT NULL
                  )
                """
            )
            rejected_reset = cursor.rowcount

            # 3. Promote to 'Rejected' for any application with a rejection email where rejection is the latest decision
            cursor.execute(
                """
                UPDATE applications
                SET status = 'Rejected', updated_at = CURRENT_TIMESTAMP
                WHERE id IN (
                    SELECT DISTINCT application_id FROM email_interactions WHERE category = 'rejection' AND application_id IS NOT NULL
                )
                  AND (
                      status != 'Rejected'
                      AND (
                          id NOT IN (SELECT DISTINCT application_id FROM email_interactions WHERE category = 'interview_invitation' AND application_id IS NOT NULL)
                          OR (
                              SELECT received_time FROM email_interactions WHERE application_id = applications.id AND category = 'rejection' ORDER BY received_time DESC LIMIT 1
                          ) >= (
                              SELECT received_time FROM email_interactions WHERE application_id = applications.id AND category = 'interview_invitation' ORDER BY received_time DESC LIMIT 1
                          )
                      )
                  )
                """
            )
            promoted_rejections = cursor.rowcount

            # 4. Reset 'Applied' status to 'Saved' for any application with 0 emails
            cursor.execute(
                """
                UPDATE applications
                SET status = 'Saved', updated_at = CURRENT_TIMESTAMP
                WHERE status = 'Applied'
                  AND id NOT IN (
                      SELECT DISTINCT application_id FROM email_interactions WHERE application_id IS NOT NULL
                  )
                """
            )
            applied_reset = cursor.rowcount

            # 5. Purge ghost / empty applications that have 0 emails, no archive snapshot, and no job URL
            cursor.execute(
                """
                DELETE FROM applications
                WHERE id NOT IN (SELECT DISTINCT application_id FROM email_interactions WHERE application_id IS NOT NULL)
                  AND (notes IS NULL OR (notes NOT LIKE '%Archived:%' AND notes NOT LIKE '%.md%'))
                  AND (job_url IS NULL OR TRIM(job_url) = '')
                """
            )
            purged_empty = cursor.rowcount

            conn.commit()
            return interview_reset + rejected_reset + promoted_rejections + applied_reset + purged_empty

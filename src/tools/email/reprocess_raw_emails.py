"""High-performance multi-threaded pipeline to cleanly reprocess persisted raw emails,
wipe derived classifications, and reconstruct canonical applications using an offline
Producer-Worker-Consumer architecture.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import queue
import re
import sqlite3
import sys
import threading
from typing import Any, Dict, List, Optional

# Ensure repository root is on sys.path
root_dir = str(Path(__file__).resolve().parents[3])
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from src.core.config import load_config
from src.core.location_extractor import extract_location
from src.core.normalizer import (
    is_noise_company,
    normalize_company_name,
    normalize_role_title,
)
from src.core.storage import JobAgentStorage, UNKNOWN_ROLE
from src.tools.email.adapters import EmailRecord
from src.tools.email.classifier import ClassificationResult, EmailClassifier
from src.tools.role_extractor import extract_role_from_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("reprocess_raw_emails")


@dataclass
class ClassifiedEmailTask:
    seq_num: int
    record: EmailRecord
    effective_category: str
    canon_company: str
    canon_role: Optional[str]
    cand_location: Optional[str]
    classification: ClassificationResult


def _classify_worker(
    task: tuple[int, EmailRecord],
    classifier: EmailClassifier,
    enable_llm_fallback: bool = False,
) -> ClassifiedEmailTask:
    """CPU/inference stage: Classifies an email and extracts normalized entities."""
    seq_num, record = task
    classification = classifier.classify(
        subject=record.subject,
        body=record.body,
        sender_name=record.sender_name,
        sender_email=record.sender_email,
        enable_llm_fallback=enable_llm_fallback,
    )

    effective_folder = (getattr(record, "folder", None) or "Bewerbung").strip()
    is_inbox_folder = effective_folder.lower() == "inbox"
    is_bewerbung_folder = effective_folder.lower() in ["bewerbung", "bewerbungen", "applications"]

    # BUSINESS RULE: In Inbox folder, only look for genuine interview invitations
    if is_inbox_folder and classification.category != "interview_invitation":
        return ClassifiedEmailTask(
            seq_num=seq_num,
            record=record,
            effective_category="noise",
            canon_company="",
            canon_role=None,
            cand_location=None,
            classification=classification,
        )

    cand_company = classification.matched_company
    if classification.category == "noise":
        canon_company = ""
        canon_role = None
        effective_category = "noise"
        cand_location = None
    else:
        if not cand_company or is_noise_company(cand_company):
            extracted = classifier.extract_company_from_context(
                record.subject, record.sender_name, record.sender_email
            )
            if extracted and not is_noise_company(extracted):
                cand_company = extracted

        if not cand_company and is_bewerbung_folder:
            if record.sender_name and not is_noise_company(record.sender_name):
                cand_company = record.sender_name

        canon_company = normalize_company_name(cand_company)
        if is_noise_company(canon_company):
            canon_company = ""

        canon_role = normalize_role_title(classification.matched_role)
        if not canon_role:
            m_role = re.search(r"(?:to|as)\s+(.+?)\s+at\s+", record.subject, re.IGNORECASE)
            if m_role:
                canon_role = normalize_role_title(m_role.group(1).strip())

        if not canon_role:
            cand_role = extract_role_from_context(record.subject, record.body, use_llm=enable_llm_fallback)
            if cand_role and cand_role != UNKNOWN_ROLE:
                cand_role = re.sub(r"\s+(?:bei|at|für|fuer)\s+.*$", "", cand_role, flags=re.IGNORECASE)
                canon_role = normalize_role_title(cand_role)

        cand_location = extract_location(record.subject, record.body, canon_role) if canon_company else None
        effective_category = classification.category

    return ClassifiedEmailTask(
        seq_num=seq_num,
        record=record,
        effective_category=effective_category,
        canon_company=canon_company,
        canon_role=canon_role,
        cand_location=cand_location,
        classification=classification,
    )


def _producer_loop(
    records: List[EmailRecord],
    task_queue: queue.Queue,
    num_workers: int,
) -> None:
    """Grinds through emails sequentially in strict chronological order and queues them."""
    for idx, rec in enumerate(records):
        task_queue.put((idx, rec))
    # Place one sentinel per worker
    for _ in range(num_workers):
        task_queue.put(None)


def _worker_loop(
    task_queue: queue.Queue,
    results_queue: queue.Queue,
    comp_map: Dict[str, Dict[str, Any]],
    enable_llm_fallback: bool = False,
) -> None:
    """Worker thread running offline ML & rule classification concurrently."""
    classifier = EmailClassifier()
    classifier.set_applied_companies(comp_map)

    while True:
        task = task_queue.get()
        if task is None:
            break
        try:
            res = _classify_worker(task, classifier, enable_llm_fallback)
            results_queue.put(res)
        except Exception as e:
            log.warning("Worker error on seq %d: %s", task[0], e, exc_info=True)
            seq_num, record = task
            results_queue.put(
                ClassifiedEmailTask(
                    seq_num=seq_num,
                    record=record,
                    effective_category="follow_up",
                    canon_company="",
                    canon_role=None,
                    cand_location=None,
                    classification=ClassificationResult(
                        category="follow_up",
                        confidence=0.5,
                        explanation=f"Error in processing: {e}",
                    ),
                )
            )


def _commit_single_task(
    task: ClassifiedEmailTask,
    storage: JobAgentStorage,
    comp_map: Dict[str, Dict[str, Any]],
    summary: Dict[str, Any],
) -> None:
    record = task.record
    canon_company = task.canon_company
    canon_role = task.canon_role
    effective_category = task.effective_category
    cand_location = task.cand_location
    classification = task.classification

    effective_folder = (getattr(record, "folder", None) or "Bewerbung").strip().lower()
    is_inbox_folder = effective_folder == "inbox"

    # USER BUSINESS RULE: From Inbox, only pick up genuine interview invitations.
    # Personal banking emails, newsletters, and noise must be ignored and never recorded.
    if is_inbox_folder and effective_category != "interview_invitation":
        summary["total_processed"] += 1
        summary["noise"] += 1
        return

    app_id = None
    if canon_company:
        existing_app = storage.get_application_by_company(
            company=canon_company,
            role=canon_role,
            date=record.received_time,
            category=effective_category,
        )
        initial_status = "Applied"
        if effective_category == "interview_invitation":
            initial_status = "Interview"
        elif effective_category == "rejection":
            initial_status = "Rejected"

        if existing_app:
            app_id = existing_app["id"]
            existing_notes = str(existing_app.get("notes") or "").lower()
            is_manual_rejection = "phone" in existing_notes or "manual" in existing_notes
            if effective_category == "interview_invitation":
                if not is_manual_rejection:
                    storage.update_application_status(app_id, "Interview")
            elif effective_category == "rejection":
                storage.update_application_status(
                    app_id, "Rejected", notes=f"Rejection email on {record.received_time}"
                )
            if canon_role and not normalize_role_title(existing_app.get("role")):
                with storage._get_connection() as conn:
                    conn.execute("UPDATE applications SET role = ? WHERE id = ?", (canon_role, app_id))
                    conn.commit()
            if cand_location and (not existing_app.get("location") or existing_app.get("location") == "—"):
                with storage._get_connection() as conn:
                    conn.execute("UPDATE applications SET location = ? WHERE id = ?", (cand_location, app_id))
                    conn.commit()
        else:
            effective_folder = (getattr(record, "folder", None) or "Bewerbung").strip()
            app_id = storage.upsert_application(
                company=canon_company,
                role=canon_role or UNKNOWN_ROLE,
                applied_date=record.received_time,
                status=initial_status,
                source=f"Email ({effective_folder})",
                location=cand_location,
            )
            if comp_map is not None:
                comp_map[canon_company.strip().lower()] = {
                    "id": app_id,
                    "company": canon_company,
                    "role": canon_role or UNKNOWN_ROLE,
                }

    # Record email interaction with traceability link to canonical application
    storage.record_email_interaction(
        entry_id=record.entry_id,
        category=effective_category,
        sender_name=record.sender_name,
        sender_email=record.sender_email,
        subject=record.subject,
        received_time=record.received_time,
        preview=record.preview,
        application_id=app_id,
        confidence_score=classification.confidence,
        action_taken=classification.explanation,
        reasoning=classification.reasoning or classification.explanation,
        intent=classification.intent or effective_category,
    )

    # Record interview if actionable
    if effective_category == "interview_invitation" and canon_company:
        sched_date = classification.suggested_date or record.received_time
        res = storage.record_interview(
            company=canon_company,
            interview_date=sched_date,
            role=canon_role or UNKNOWN_ROLE,
            application_id=app_id,
            interview_type="Interview Invitation",
            meeting_link=classification.meeting_link,
            status="Pending_Confirmation",
            notes=f"Detected from email: {record.subject}",
            entry_id=record.entry_id,
        )
        interview_id, created = res if isinstance(res, tuple) else (res, True)
        if created:
            summary["actionable_alerts"].append({
                "type": "interview_invitation",
                "interview_id": interview_id,
                "company": canon_company,
                "subject": record.subject,
                "meeting_link": classification.meeting_link,
                "scheduled_date": sched_date,
            })
    elif effective_category == "rejection" and app_id:
        storage.update_application_status(
            app_id, "Rejected", notes=f"Rejection email on {record.received_time}"
        )

    summary["total_processed"] += 1
    if effective_category == "application_confirmation":
        summary["confirmations"] += 1
    elif effective_category == "rejection":
        summary["rejections"] += 1
    elif effective_category == "interview_invitation":
        summary["interviews"] += 1
    elif effective_category == "follow_up":
        summary["follow_ups"] += 1
    else:
        summary["noise"] += 1


def _consume_and_write(
    results_queue: queue.Queue,
    total_count: int,
    storage: JobAgentStorage,
    comp_map: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Consumer thread: Reassembles tasks in strict chronological order and writes to SQLite."""
    summary = {
        "total_processed": 0,
        "confirmations": 0,
        "rejections": 0,
        "interviews": 0,
        "follow_ups": 0,
        "noise": 0,
        "actionable_alerts": [],
    }

    buffer: Dict[int, ClassifiedEmailTask] = {}
    expected_seq = 0

    while expected_seq < total_count:
        item = results_queue.get()
        buffer[item.seq_num] = item

        while expected_seq in buffer:
            task = buffer.pop(expected_seq)
            _commit_single_task(task, storage, comp_map, summary)
            expected_seq += 1
            if expected_seq % 100 == 0 or expected_seq == total_count:
                log.info(
                    "Progress: %d/%d emails classified and committed (rejections: %d, confirmations: %d, interviews: %d)...",
                    expected_seq,
                    total_count,
                    summary["rejections"],
                    summary["confirmations"],
                    summary["interviews"],
                )

    return summary


def reprocess_raw_emails(
    db_path: str = "data/jobagent.db",
    num_workers: int = 4,
    enable_llm_fallback: bool = False,
) -> Dict[str, Any]:
    """Wipes derived classifications, then runs the multi-threaded pipeline across all raw_emails."""
    log.info("Connecting to database: %s", db_path)
    storage = JobAgentStorage(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM raw_emails")
        raw_count = cur.fetchone()[0]
        log.info("Found %d persisted raw emails in database.", raw_count)

        if raw_count == 0:
            log.warning("No raw emails found to reprocess.")
            return {"status": "empty", "raw_count": 0}


        # 2. Delete phantom applications and duplicate applications
        phantom_names = [
            "your application",
            "we've received your application",
            "we’ve received your application",
            "application",
            "application confirmation",
            "ihre bewerbung",
            "deine bewerbung",
            "bewerbung",
            "bundesagentur für arbeit",
            "bundesagentur fuer arbeit",
            "arbeitsagentur",
            "arbeitsagentur.de",
            "jobcenter",
        ]
        placeholders = ",".join(["?"] * len(phantom_names))
        cur.execute(
            f"DELETE FROM applications WHERE LOWER(TRIM(company)) IN ({placeholders})",
            phantom_names,
        )
        cur.execute(
            """
            DELETE FROM applications 
            WHERE id > 266 
              AND LOWER(TRIM(company)) IN (
                  SELECT LOWER(TRIM(company)) FROM applications WHERE id <= 266
              )
            """
        )
        cur.execute(
            """
            DELETE FROM applications 
            WHERE id > 266 
              AND id NOT IN (SELECT DISTINCT application_id FROM email_interactions WHERE application_id IS NOT NULL)
              AND (job_url IS NULL OR job_url = '') 
              AND (notes IS NULL OR notes NOT LIKE 'Archived:%')
            """
        )
        deleted_phantoms = cur.rowcount
        conn.commit()

        # 3. Clean derived data tables (email_interactions and auto-detected interviews)
        cur.execute("DELETE FROM email_interactions")
        wiped_interactions = cur.rowcount
        log.info("Wiped %d stale email_interactions.", wiped_interactions)

        cur.execute(
            """
            DELETE FROM interviews 
            WHERE entry_id IS NOT NULL 
               OR interview_type = 'Interview Invitation'
            """
        )
        wiped_interviews = cur.rowcount
        log.info("Wiped %d auto-detected interview records.", wiped_interviews)
        conn.commit()

        # 4. Fetch all raw emails ordered by received_time ASC
        cur.execute(
            """
            SELECT entry_id, folder, sender_name, sender_email, subject, body, preview, received_time
            FROM raw_emails
            ORDER BY received_time ASC
            """
        )
        raw_rows = cur.fetchall()

    records: List[EmailRecord] = [
        EmailRecord(
            entry_id=r["entry_id"],
            sender_name=r["sender_name"] or "",
            sender_email=r["sender_email"] or "",
            subject=r["subject"] or "",
            received_time=r["received_time"] or "",
            body=r["body"] or "",
            preview=r["preview"] or "",
            folder=r["folder"] or "Bewerbung",
        )
        for r in raw_rows
    ]

    # Build initial in-memory company lookup from baseline applications
    apps = storage.list_applications()
    comp_map = {
        app["company"].strip().lower(): app
        for app in apps
        if app.get("company") and len(app["company"]) >= 2
    }

    # 5. Run Producer-Worker-Consumer multi-threaded pipeline
    log.info(
        "Starting multi-threaded pipeline: %d records, %d worker threads (ML Tier enabled)...",
        len(records),
        num_workers,
    )
    task_queue: queue.Queue = queue.Queue(maxsize=100)
    results_queue: queue.Queue = queue.Queue(maxsize=200)

    # Start Producer Thread
    producer_thread = threading.Thread(
        target=_producer_loop,
        args=(records, task_queue, num_workers),
        name="EmailProducer",
    )
    producer_thread.start()

    # Start Classification Worker Pool
    workers = [
        threading.Thread(
            target=_worker_loop,
            args=(task_queue, results_queue, comp_map, enable_llm_fallback),
            name=f"ClassifierWorker-{i}",
        )
        for i in range(num_workers)
    ]
    for w in workers:
        w.start()

    # Consumer / Writer executes in main thread
    cluster_res = _consume_and_write(
        results_queue=results_queue,
        total_count=len(records),
        storage=storage,
        comp_map=comp_map,
    )

    # Wait for threads to join
    producer_thread.join()
    for w in workers:
        w.join()

    log.info(
        "Pipeline complete: %d scanned, %d confirmations, %d interviews, %d rejections, %d follow_ups, %d noise.",
        cluster_res["total_processed"],
        cluster_res["confirmations"],
        cluster_res["interviews"],
        cluster_res["rejections"],
        cluster_res["follow_ups"],
        cluster_res["noise"],
    )

    # 6. Reconcile unlinked interactions against existing applications
    log.info("Running storage.reconcile_unlinked()...")
    reconcile_res = storage.reconcile_unlinked()
    log.info("Reconciliation result: %s", reconcile_res)

    # 6b. Split multi-cycle applications where a rejection is followed by a later application confirmation
    log.info("Running storage.split_multi_cycle_applications()...")
    split_res = storage.split_multi_cycle_applications()
    log.info("Split result: %s", split_res)

    # 6c. Sync unapplied / unrejected statuses to guarantee accuracy (Saved vs Applied vs Rejected)
    log.info("Running storage.sync_unapplied_archive_statuses()...")
    synced_statuses = storage.sync_unapplied_archive_statuses()
    log.info("Synchronized %d application statuses.", synced_statuses)


    # 7. Post-reprocessing stats & validation
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM email_interactions WHERE application_id IS NOT NULL")
        linked_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM email_interactions WHERE application_id IS NULL")
        unlinked_count = cur.fetchone()[0]

        cur.execute(
            """
            SELECT a.id, a.company, a.role, a.status, COUNT(e.id) as email_count
            FROM applications a
            LEFT JOIN email_interactions e ON a.id = e.application_id
            WHERE LOWER(a.company) LIKE '%invenio%' 
               OR LOWER(a.company) LIKE '%genki%'
               OR LOWER(a.company) LIKE '%code compass%'
               OR LOWER(a.company) LIKE '%starmate%'
               OR LOWER(a.company) LIKE '%infosys%'
               OR LOWER(a.company) LIKE '%operations1%'
               OR LOWER(a.company) LIKE '%westernacher%'
               OR LOWER(a.company) LIKE '%nxt hero%'
               OR LOWER(a.company) LIKE '%cargomotion%'
               OR LOWER(a.company) LIKE '%dekabank%'
               OR LOWER(a.company) LIKE '%bundesagentur%'
            GROUP BY a.id
            ORDER BY a.company, a.id
            """
        )
        target_check = [dict(r) for r in cur.fetchall()]

    log.info("Post-reprocessing stats: %d linked interactions, %d unlinked interactions.", linked_count, unlinked_count)

    return {
        "raw_count": raw_count,
        "deleted_phantoms": deleted_phantoms,
        "cluster_res": cluster_res,
        "reconcile_res": reconcile_res,
        "linked_count": linked_count,
        "unlinked_count": unlinked_count,
        "target_check": target_check,
    }


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    db = cfg.storage.database_path if hasattr(cfg, "storage") else "data/jobagent.db"
    res = reprocess_raw_emails(db)
    print("\nReprocessing Summary:\n", res)

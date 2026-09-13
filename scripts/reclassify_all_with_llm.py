"""
Reclassifies email interactions using Gemini LLM semantic intent reasoning.
Populates intent, category, confidence_score, and chain-of-thought reasoning in SQLite.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()

from src.core.config import load_config
from src.core.llm_provider import call_gemini_semantic_analysis
from src.tools.email.classifier import EmailClassifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("reclassify_emails")


def reclassify_emails(
    db_path: str = "data/jobagent.db",
    limit: Optional[int] = None,
    only_unreasoned: bool = False,
    company_filter: Optional[str] = None,
) -> Dict[str, Any]:
    cfg = load_config()
    classifier = EmailClassifier()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
        SELECT 
            e.id, 
            e.entry_id, 
            e.application_id, 
            e.sender_name, 
            e.sender_email, 
            e.subject, 
            e.received_time, 
            e.category, 
            e.confidence_score, 
            e.reasoning,
            COALESCE(r.body, e.preview, '') AS body,
            a.company AS app_company
        FROM email_interactions e
        LEFT JOIN raw_emails r ON e.entry_id = r.entry_id
        LEFT JOIN applications a ON e.application_id = a.id
        WHERE 1=1
    """
    params: List[Any] = []
    if only_unreasoned:
        query += " AND (e.reasoning IS NULL OR TRIM(e.reasoning) = '' OR e.reasoning LIKE 'marked_%')"
    if company_filter:
        query += " AND LOWER(a.company) LIKE ?"
        params.append(f"%{company_filter.lower()}%")

    query += " ORDER BY e.id DESC"
    if limit:
        query += f" LIMIT {int(limit)}"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    log.info("Found %d email interactions to evaluate with LLM.", len(rows))

    stats = {
        "total": len(rows),
        "reclassified": 0,
        "rejections": 0,
        "interviews": 0,
        "confirmations": 0,
        "other": 0,
        "errors": 0,
    }

    for idx, row in enumerate(rows, 1):
        interaction_id = row["id"]
        app_id = row["application_id"]
        subject = row["subject"] or ""
        sender_name = row["sender_name"] or ""
        sender_email = row["sender_email"] or ""
        body = row["body"] or ""
        app_company = row["app_company"] or ""

        log.info("[%d/%d] Evaluating interaction #%d (%s - %s)...", idx, len(rows), interaction_id, app_company, subject[:40])

        try:
            res = classifier.classify_with_llm(
                subject=subject,
                body=body,
                sender_name=sender_name,
                sender_email=sender_email,
            )

            if res:
                category = res.category
                intent = res.intent or res.category
                confidence = float(res.confidence)
                reasoning = res.reasoning or res.explanation or f"Classified as {intent}"

                cursor.execute(
                    """
                    UPDATE email_interactions
                    SET category = ?,
                        intent = ?,
                        confidence_score = ?,
                        reasoning = ?,
                        action_taken = ?
                    WHERE id = ?
                    """,
                    (category, intent, confidence, reasoning, reasoning, interaction_id),
                )
                conn.commit()

                # Promoted / Updated Status
                if category == "rejection" and app_id:
                    cursor.execute("UPDATE applications SET status = 'Rejected', updated_at = datetime('now') WHERE id = ? AND status != 'Interview'", (app_id,))
                    stats["rejections"] += 1
                elif category == "interview_invitation" and app_id:
                    cursor.execute("UPDATE applications SET status = 'Interview', updated_at = datetime('now') WHERE id = ?", (app_id,))
                    stats["interviews"] += 1
                elif category == "application_confirmation":
                    stats["confirmations"] += 1
                else:
                    stats["other"] += 1

                stats["reclassified"] += 1
                log.info("  ✓ Result: %s (%.0f%%) | %s", category.upper(), confidence * 100, reasoning[:70])
            else:
                log.warning("  ⚠ LLM did not return a valid result for #%d", interaction_id)
                stats["errors"] += 1

        except Exception as e:
            log.error("  ✕ Error evaluating interaction #%d: %s", interaction_id, e)
            stats["errors"] += 1

    conn.close()
    log.info("Completed LLM reclassification: %s", stats)
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reclassify emails with Gemini LLM.")
    parser.add_argument("--db", default="data/jobagent.db", help="Path to SQLite DB")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of emails to evaluate")
    parser.add_argument("--only-unreasoned", action="store_true", help="Only reclassify emails without reasoning")
    parser.add_argument("--company", type=str, default=None, help="Filter by company name")
    args = parser.parse_args()

    reclassify_emails(
        db_path=args.db,
        limit=args.limit,
        only_unreasoned=args.only_unreasoned,
        company_filter=args.company,
    )

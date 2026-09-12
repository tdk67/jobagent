"""Application threading and deduplication clustering engine.

Groups multiple emails related to the same job application:
- Application confirmation (LinkedIn, StepStone, or direct ATS)
- Email verifications and GDPR/privacy notices
- Portal activation links
- Status updates and recruiter inquiries
- Rejections or Interview invitations

Ensures:
1. Each distinct job application is represented exactly once.
2. Legal suffixes and aggregator noise are eliminated.
3. Every classified interaction links back to the original email entry_id for auditability.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.core.storage import JobAgentStorage, UNKNOWN_ROLE
from src.tools.email.adapters import EmailRecord
from src.tools.email.classifier import ClassificationResult, EmailClassifier
from src.tools.email.normalizer import (
    is_noise_company,
    normalize_company_name,
    normalize_role_title,
)

log = logging.getLogger(__name__)


class ApplicationClusterer:
    """Clusters incoming or cached emails into canonical job application entities."""

    def __init__(
        self,
        storage: JobAgentStorage,
        classifier: Optional[EmailClassifier] = None,
    ):
        self.storage = storage
        self.classifier = classifier or EmailClassifier()

    def _refresh_applied_companies(self) -> Dict[str, Dict[str, Any]]:
        apps = self.storage.list_applications()
        comp_map = {
            app["company"].strip().lower(): app
            for app in apps
            if app.get("company") and len(app["company"]) >= 2
        }
        self.classifier.set_applied_companies(comp_map)
        return comp_map

    def process_email(
        self,
        record: EmailRecord,
        folder: str = "Bewerbung",
        enable_llm_fallback: bool = False,
    ) -> Dict[str, Any]:
        """Classifies a single email, normalizes entities, and merges into canonical application."""
        comp_map = self._refresh_applied_companies()

        classification = self.classifier.classify(
            subject=record.subject,
            body=record.body,
            sender_name=record.sender_name,
            sender_email=record.sender_email,
            enable_llm_fallback=enable_llm_fallback,
        )

        is_bewerbung_folder = folder.lower() in ["bewerbung", "bewerbungen", "applications"]

        # Extract & normalize candidate company
        cand_company = classification.matched_company
        if classification.category == "noise":
            canon_company = ""
            canon_role = None
            effective_category = "noise"
        else:
            if not cand_company or is_noise_company(cand_company):
                # Try extracting from context or sender domain
                extracted = self.classifier.extract_company_from_context(
                    record.subject, record.sender_name, record.sender_email
                )
                if extracted and not is_noise_company(extracted):
                    cand_company = extracted

            # If still no company found and it's in Bewerbung folder, try sender name
            if not cand_company and is_bewerbung_folder:
                if record.sender_name and not is_noise_company(record.sender_name):
                    cand_company = record.sender_name

            canon_company = normalize_company_name(cand_company)
            if is_noise_company(canon_company):
                canon_company = ""

            # Normalize role
            canon_role = normalize_role_title(classification.matched_role)
            if not canon_role:
                from src.core.storage import UNKNOWN_ROLE
                from src.tools.role_extractor import extract_role_from_context
                import re
                cand_role = extract_role_from_context(record.subject, record.body)
                if cand_role and cand_role != UNKNOWN_ROLE:
                    cand_role = re.sub(r"\s+(?:bei|at|für|fuer)\s+.*$", "", cand_role, flags=re.IGNORECASE)
                    canon_role = normalize_role_title(cand_role)

            effective_category = classification.category

        app_id = None
        if canon_company:
            # Check existing application in DB
            existing_app = self.storage.get_application_by_company(canon_company)
            initial_status = "Applied"
            if effective_category == "interview_invitation":
                initial_status = "Interview"
            elif effective_category == "rejection":
                initial_status = "Rejected"

            app_id = self.storage.upsert_application(
                company=canon_company,
                role=canon_role or UNKNOWN_ROLE,
                applied_date=record.received_time,
                status=initial_status,
                source=f"Email ({folder})",
            )

        # Record email interaction with traceability link to canonical application
        self.storage.record_email_interaction(
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
        )

        # Handle specific events
        interview_alert = None
        if effective_category == "interview_invitation" and canon_company:
            sched_date = classification.suggested_date or record.received_time
            res = self.storage.record_interview(
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
                interview_alert = {
                    "type": "interview_invitation",
                    "interview_id": interview_id,
                    "company": canon_company,
                    "subject": record.subject,
                    "meeting_link": classification.meeting_link,
                    "scheduled_date": sched_date,
                }
        elif effective_category == "rejection" and app_id:
            self.storage.update_application_status(
                app_id, "Rejected", notes=f"Rejection email on {record.received_time}"
            )

        return {
            "entry_id": record.entry_id,
            "category": effective_category,
            "company": canon_company or None,
            "role": canon_role or None,
            "application_id": app_id,
            "interview_alert": interview_alert,
        }

    def cluster_batch(
        self,
        records: List[EmailRecord],
        folder: str = "Bewerbung",
        enable_llm_fallback: bool = False,
    ) -> Dict[str, Any]:
        """Clusters a collection of emails into deduplicated canonical applications."""
        summary = {
            "total_processed": 0,
            "confirmations": 0,
            "rejections": 0,
            "interviews": 0,
            "follow_ups": 0,
            "noise": 0,
            "actionable_alerts": [],
        }

        for rec in records:
            res = self.process_email(
                record=rec,
                folder=folder,
                enable_llm_fallback=enable_llm_fallback,
            )
            summary["total_processed"] += 1
            cat = res["category"]
            if cat == "application_confirmation":
                summary["confirmations"] += 1
            elif cat == "rejection":
                summary["rejections"] += 1
            elif cat == "interview_invitation":
                summary["interviews"] += 1
            elif cat == "follow_up":
                summary["follow_ups"] += 1
            else:
                summary["noise"] += 1

            if res.get("interview_alert"):
                summary["actionable_alerts"].append(res["interview_alert"])

        return summary

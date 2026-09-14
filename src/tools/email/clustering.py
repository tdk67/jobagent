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

import json
import logging
import re
from typing import Any, Dict, List, Optional

from src.core.storage import JobAgentStorage, UNKNOWN_ROLE
from src.tools.email.adapters import EmailRecord
from src.tools.email.classifier import ClassificationResult, EmailClassifier
from src.core.normalizer import (
    is_noise_company,
    normalize_company_name,
    normalize_role_title,
)

log = logging.getLogger(__name__)


class ApplicationClusterer:
    """Clusters incoming or cached emails into canonical job application entities.

    Batched LLM tier: when a batch contains multiple rule-ambiguous emails, they
    are sent to Gemini in ONE combined call (schema-only), cutting the per-email
    LLM cost to a fraction and avoiding per-call rate limits.
    """

    def __init__(
        self,
        storage: JobAgentStorage,
        classifier: Optional[EmailClassifier] = None,
    ):
        self.storage = storage
        self.classifier = classifier or EmailClassifier()
        self._comp_map: Optional[Dict[str, Dict[str, Any]]] = None
        # entry_id -> ClassificationResult from a batched LLM pass (single API call)
        self._batch_llm_results: Dict[str, ClassificationResult] = {}

    def _refresh_applied_companies(self, force: bool = False) -> Dict[str, Dict[str, Any]]:
        if self._comp_map is not None and not force:
            return self._comp_map
        apps = self.storage.list_applications()
        comp_map = {
            app["company"].strip().lower(): app
            for app in apps
            if app.get("company") and len(app["company"]) >= 2
        }
        self._comp_map = comp_map
        self.classifier.set_applied_companies(comp_map)
        return comp_map

    def process_email(
        self,
        record: EmailRecord,
        folder: str = "Bewerbung",
        enable_llm_fallback: bool = False,
    ) -> Dict[str, Any]:
        """Classifies a single email, normalizes entities, and merges into canonical application.

        If a batched LLM classification was pre-computed for this entry_id (one
        shared API call), it is used instead of issuing a fresh per-email LLM call.
        """
        comp_map = self._refresh_applied_companies()

        cached = self._batch_llm_results.get(record.entry_id)
        if cached is not None:
            classification = cached
        else:
            classification = self.classifier.classify(
                subject=record.subject,
                body=record.body,
                sender_name=record.sender_name,
                sender_email=record.sender_email,
                enable_llm_fallback=enable_llm_fallback,
            )

        # When a batched LLM result is available, skip the slow per-email role LLM
        # fallback too — the batch already decided the role/company semantics.
        role_llm_ok = enable_llm_fallback and cached is None

        effective_folder = (getattr(record, "folder", None) or folder).strip()
        is_inbox_folder = effective_folder.lower() == "inbox"
        is_bewerbung_folder = effective_folder.lower() in ["bewerbung", "bewerbungen", "applications"]

        # USER BUSINESS RULE:
        # In folder "Inbox", check ONLY for genuine interview requests/invitations.
        # Non-interview emails in Inbox (newsletters, portal updates, general notifications like Bundesagentur)
        # must be discarded as noise, never creating an application or polluting the application ledger.
        if is_inbox_folder and classification.category != "interview_invitation":
            return {
                "entry_id": record.entry_id,
                "category": "noise",
                "company": None,
                "role": None,
                "application_id": None,
                "interview_alert": None,
            }

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
                # Check for portal pattern "to {role} at {company}"
                m_role = re.search(r"(?:to|as)\s+(.+?)\s+at\s+", record.subject, re.IGNORECASE)
                if m_role:
                    canon_role = normalize_role_title(m_role.group(1).strip())

            if not canon_role:
                from src.core.storage import UNKNOWN_ROLE
                from src.tools.role_extractor import extract_role_from_context
                cand_role = extract_role_from_context(record.subject, record.body, use_llm=role_llm_ok)
                if cand_role and cand_role != UNKNOWN_ROLE:
                    cand_role = re.sub(r"\s+(?:bei|at|für|fuer)\s+.*$", "", cand_role, flags=re.IGNORECASE)
                    canon_role = normalize_role_title(cand_role)

            effective_category = classification.category

        app_id = None
        if canon_company:
            from src.core.location_extractor import extract_location
            cand_location = extract_location(record.subject, record.body, canon_role)

            # Check existing application in DB with multi-application role + date + lifecycle disambiguation
            existing_app = self.storage.get_application_by_company(
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
                if effective_category == "interview_invitation":
                    self.storage.update_application_status(app_id, "Interview")
                elif effective_category == "rejection" and existing_app.get("status") != "Interview":
                    self.storage.update_application_status(
                        app_id, "Rejected", notes=f"Rejection email on {record.received_time}"
                    )
                if canon_role and not normalize_role_title(existing_app.get("role")):
                    with self.storage._get_connection() as conn:
                        conn.execute("UPDATE applications SET role = ? WHERE id = ?", (canon_role, app_id))
                        conn.commit()
                if cand_location and (not existing_app.get("location") or existing_app.get("location") == "—"):
                    with self.storage._get_connection() as conn:
                        conn.execute("UPDATE applications SET location = ? WHERE id = ?", (cand_location, app_id))
                        conn.commit()
            else:
                app_id = self.storage.upsert_application(
                    company=canon_company,
                    role=canon_role or UNKNOWN_ROLE,
                    applied_date=record.received_time,
                    status=initial_status,
                    source=f"Email ({effective_folder})",
                    location=cand_location,
                )
                if self._comp_map is not None:
                    self._comp_map[canon_company.strip().lower()] = {
                        "id": app_id,
                        "company": canon_company,
                        "role": canon_role or UNKNOWN_ROLE,
                    }
                    self.classifier.set_applied_companies(self._comp_map)

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
            reasoning=classification.reasoning or classification.explanation,
            intent=classification.intent or effective_category,
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

    def batch_llm_classify(
        self,
        records: List[EmailRecord],
        enable_llm_fallback: bool = False,
    ) -> None:
        """Classifies the ambiguous remainder of a batch in ONE combined LLM call.

        Emails that the deterministic classifier would send to its LLM tier are
        collected and sent together as a single JSON-array prompt. Each result is
        cached by entry_id so process_email reuses it — never a per-email round
        trip. Falls back silently to per-email classification if the batch call
        is unavailable or fails.
        """
        if not enable_llm_fallback:
            return
        if not records:
            return
        try:
            import os
            if not os.getenv("GEMINI_API_KEY"):
                return
            from src.core.llm_provider import call_gemini_semantic_analysis
            from src.utils.prompt_loader import load_prompt
        except Exception as e:
            log.debug("Batch LLM not available: %s", e)
            return

        # Quick deterministic pass: only emails that WOULD go to the LLM tier
        # (i.e. career-context but low-confidence rules) are batched.
        candidates: List[EmailRecord] = []
        for rec in records:
            fast = self.classifier.classify(
                subject=rec.subject,
                body=rec.body,
                sender_name=rec.sender_name,
                sender_email=rec.sender_email,
                enable_llm_fallback=False,
            )
            if fast.category in ("follow_up", "noise") and fast.confidence < 0.8:
                # ambiguous under pure rules -> let the batched LLM decide
                candidates.append(rec)

        if not candidates:
            return

        emails_payload = []
        for rec in candidates:
            emails_payload.append(
                {
                    "entry_id": rec.entry_id,
                    "sender_name": rec.sender_name,
                    "sender_email": rec.sender_email,
                    "subject": rec.subject,
                    "body": rec.body[:1500],
                }
            )

        try:
            prompt_template = load_prompt("email_classifier_batch.txt")
            prompt = prompt_template.replace("{{emails}}", json.dumps(emails_payload, ensure_ascii=False))
        except Exception:
            prompt = (
                "You are an expert recruitment triage assistant. Classify each email below. "
                "Return ONLY a JSON array, one object per email, each with keys: "
                "entry_id, category (interview_invitation|application_confirmation|rejection|follow_up|noise|verification), "
                "confidence (0-1), matched_company, matched_role, meeting_link, suggested_date, reasoning.\n\n"
                f"Emails:\n{json.dumps(emails_payload, ensure_ascii=False)}"
            )

        res_text = call_gemini_semantic_analysis(prompt)
        if not res_text:
            return

        cleaned = res_text.strip()
        for fence in ("```json", "```"):
            if fence in cleaned:
                cleaned = cleaned.split(fence)[1].split("```")[0].strip()
                break
        try:
            parsed_list = json.loads(cleaned)
        except Exception as e:
            log.warning("Batch LLM response not parseable: %s", e)
            return
        if not isinstance(parsed_list, list):
            return

        valid_cats = {"interview_invitation", "application_confirmation", "rejection", "follow_up", "noise", "verification"}
        for item in parsed_list:
            if not isinstance(item, dict) or not item.get("entry_id"):
                continue
            cat = item.get("category")
            if cat not in valid_cats:
                cat = "noise"
            try:
                conf = float(item.get("confidence", 0.9))
                if conf > 1.0:
                    conf /= 100.0
            except (TypeError, ValueError):
                conf = 0.9
            reasoning = item.get("reasoning") or item.get("explanation") or "Classified via batched LLM"
            self._batch_llm_results[item["entry_id"]] = ClassificationResult(
                category=cat,
                confidence=conf,
                matched_company=item.get("matched_company") or None,
                matched_role=item.get("matched_role") or None,
                meeting_link=self.classifier.extract_meeting_link(item.get("meeting_link") or "") or None,
                suggested_date=item.get("suggested_date") or None,
                explanation=reasoning,
                intent=cat,
                reasoning=reasoning,
            )
        log.info("Batched LLM classified %d ambiguous emails in 1 call", len(self._batch_llm_results))

    def cluster_batch(
        self,
        records: List[EmailRecord],
        folder: str = "Bewerbung",
        enable_llm_fallback: bool = False,
    ) -> Dict[str, Any]:
        """Clusters a collection of emails into deduplicated canonical applications."""
        # Batched LLM tier: classify ambiguous remainder in ONE combined call.
        self._batch_llm_results = {}
        self.batch_llm_classify(records, enable_llm_fallback)

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

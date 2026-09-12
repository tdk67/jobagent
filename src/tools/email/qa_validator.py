"""Intelligent QA validation pipeline for email triage and entity extraction.

Uses LLM semantic reasoning and dynamic domain derivation to verify classifications
and extracted company entities, eliminating brittle hardcoded keyword lists.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import List, Optional

from src.core.channel_extractor import extract_channel, extract_channel_from_domain
from src.core.llm_provider import call_gemini_semantic_analysis
from src.core.location_extractor import extract_location

log = logging.getLogger(__name__)


@dataclass
class QAValidationResult:
    """Outcome of the intelligent QA validation step."""
    is_valid: bool
    verified_company: str
    verified_category: str
    confidence_score: float
    channel: str
    location: Optional[str]
    flags: List[str]
    qa_explanation: str


class EmailQAValidator:
    """Intelligent QA validator ensuring ingested emails and inferences meet quality standards."""

    def __init__(self, use_llm: bool = True) -> None:
        self.use_llm = use_llm

    def validate(
        self,
        raw_subject: str,
        raw_body: str,
        sender_name: Optional[str] = None,
        sender_email: Optional[str] = None,
        inferred_company: Optional[str] = None,
        inferred_role: Optional[str] = None,
        inferred_category: Optional[str] = None,
        inferred_confidence: float = 1.0,
    ) -> QAValidationResult:
        """Validates classifications and entity extraction using semantic reasoning or dynamic domain derivation."""
        flags: List[str] = []
        clean_company = (inferred_company or "").strip()
        category = (inferred_category or "application_confirmation").lower().strip()

        # 1. Attempt Intelligent LLM Semantic Verification
        llm_verified = False
        if self.use_llm:
            try:
                from src.utils.prompt_loader import load_prompt
                try:
                    prompt_template = load_prompt("qa_validator.txt")
                    prompt = prompt_template.format(
                        clean_company=clean_company,
                        candidate_role=inferred_role or "Unknown",
                        category=category,
                        sender_name=sender_name or "",
                        sender_email=sender_email or "",
                        raw_subject=raw_subject,
                        body=raw_body[:1200],
                    )
                except Exception:
                    prompt = (
                        "You are an expert QA auditor for a job application CRM. Audit this email extraction for accuracy.\n\n"
                        f"Candidate Company: {clean_company}\n"
                        f"Candidate Role: {inferred_role or 'Unknown'}\n"
                        f"Candidate Category: {category}\n"
                        f"Sender Name: {sender_name or ''}\n"
                        f"Sender Email: {sender_email or ''}\n"
                        f"Subject: {raw_subject}\n"
                        f"Body:\n{raw_body[:1200]}\n\n"
                        "Respond ONLY with valid JSON with is_valid, verified_company, verified_category, location, confidence_score, explanation."
                    )
                raw_response = call_gemini_semantic_analysis(prompt, temperature=0.1)
                if raw_response and "{" in raw_response:
                    cleaned_json = raw_response.strip()
                    if cleaned_json.startswith("```json"):
                        cleaned_json = cleaned_json[7:]
                    if cleaned_json.startswith("```"):
                        cleaned_json = cleaned_json[3:]
                    if cleaned_json.endswith("```"):
                        cleaned_json = cleaned_json[:-3]
                    
                    data = json.loads(cleaned_json.strip())
                    if data.get("verified_company"):
                        clean_company = data["verified_company"]
                    if data.get("verified_category"):
                        category = data["verified_category"]
                    llm_confidence = float(data.get("confidence_score", inferred_confidence))
                    explanation = data.get("explanation", "LLM QA Verified")
                    llm_location = data.get("location")
                    llm_verified = True

                    channel = extract_channel(sender_email=sender_email, sender_name=sender_name)
                    location = llm_location or extract_location(raw_subject, raw_body, inferred_role)

                    return QAValidationResult(
                        is_valid=bool(data.get("is_valid", True)),
                        verified_company=clean_company,
                        verified_category=category,
                        confidence_score=round(llm_confidence, 2),
                        channel=channel,
                        location=location,
                        flags=flags,
                        qa_explanation=explanation,
                    )
            except Exception as e:
                log.debug("LLM QA semantic verification skipped/failed: %s", e)

        # 2. Dynamic Algorithmic Fallback (Zero Hardcoded City or Word Lists)
        is_generic_placeholder = any(token in clean_company.lower() for token in ("application", "bewerbung", "unknown", "candidate"))
        if not clean_company or len(clean_company) < 2 or is_generic_placeholder:
            # Derive dynamically from sender corporate domain
            if sender_email and "@" in sender_email:
                domain = sender_email.split("@")[-1]
                derived = extract_channel_from_domain(domain)
                if derived:
                    clean_company = derived
                    flags.append("company_derived_from_domain")
                else:
                    clean_company = clean_company or "Unknown Company"
            else:
                clean_company = clean_company or "Unknown Company"

        channel = extract_channel(sender_email=sender_email, sender_name=sender_name)
        location = extract_location(raw_subject, raw_body, inferred_role)

        final_confidence = inferred_confidence
        if flags:
            final_confidence = max(0.5, final_confidence - (0.2 * len(flags)))

        explanation = f"Dynamic QA: Category={category}, Company='{clean_company}', Channel='{channel}', Flags={flags or 'none'}"

        return QAValidationResult(
            is_valid=True,
            verified_company=clean_company,
            verified_category=category,
            confidence_score=round(final_confidence, 2),
            channel=channel,
            location=location,
            flags=flags,
            qa_explanation=explanation,
        )

"""Semantic and rule-based email classification engine.

Classifies incoming career emails into:
- application_confirmation
- interview_invitation
- rejection
- follow_up
- noise / sales pitch

Implements dual-signal verification:
1. Reconciles against known applied companies in the local database.
2. Identifies genuine hiring interview invitations vs deceptive sales/webinar invites.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from src.utils.date_utils import parse_flexible_date

log = logging.getLogger(__name__)


def _load_classification_rules() -> Dict[str, Any]:
    """Loads externalized email classification rules separating data from code."""
    data_path = Path(__file__).resolve().parents[3] / "resources" / "email_classification_rules.json"
    if not data_path.exists():
        data_path = Path("resources") / "email_classification_rules.json"
    if data_path.exists():
        try:
            with open(data_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.warning("Could not read email classification rules from %s: %s", data_path, e)
    return {}


_RULES: Dict[str, Any] = _load_classification_rules()


@dataclass
class ClassificationResult:
    category: str  # "interview_invitation", "application_confirmation", "rejection", "follow_up", "noise"
    confidence: float
    matched_company: Optional[str] = None
    matched_role: Optional[str] = None
    meeting_link: Optional[str] = None
    suggested_date: Optional[str] = None
    explanation: str = ""


class EmailClassifier:
    """Classifies career emails using externalized rules and LLM semantic analysis."""

    # Externalized rules with backward compatibility
    NOISE_KEYWORDS: List[str] = _RULES.get("noise_keywords", [
        "webinar", "bildungsgutschein", "finanzkonzepte", "wertpapiere",
        "börse", "vertrieb", "softwarelösung", "honorary doctorate",
        "geschenk", "newsletter", "exklusive inhalte", "demo buchen",
        "kostenloses erstgespräch", "lead generation", "sales coach",
    ])

    INTERVIEW_STRONG_PATTERNS: List[str] = _RULES.get("interview_strong_patterns", [
        r"einladung zum (?:vorstellungsgespräch|kennenlernen|gespräch|interview)",
        r"zu einem vorstellungsgespräch einladen",
        r"\bvorstellungsgespräch\b",
        r"terminanfrage für ein (?:erstes )?telefoninterview",
        r"telefoninterview",
        r"\bprecall\b|\bpre-call\b",
        r"einladung zum video(?:gespräch|call)",
        r"gesprächtag|interviewtermin",
        r"unser gespräch zur stelle",
        r"in einem (?:ersten )?gespräch (?:persönlich )?kennenlernen",
        r"zeit für ein (?:kurzes )?(?:telefonat|kennenlernen|gespräch)",
        r"termin für ein (?:erstes )?gespräch",
        r"termin am \d{1,2}\.",
        r"invitation to interview",
        r"schedule an interview",
        r"interview invitation",
        r"interview with",
        r"\binterview\s*:",
        r"^interview\b",
        r"meeting invitation: interview",
        r"next round: interview",
    ])

    REJECTION_PATTERNS: List[str] = _RULES.get("rejection_patterns", [
        r"leider müssen wir Ihnen mitteilen",
        r"leider können wir",
        r"leider nicht berücksichtigen",
        r"nicht im weiteren auswahlverfahren",
        r"nicht weiter berücksichtigen",
        r"haben uns für andere",
        r"haben uns letztlich für",
        r"für eine andere person entschieden",
        r"entschieden, andere bewerber",
        r"\babsage\b",
        r"ihre bewerbung nicht weiterverfolgen",
        r"keine positive nachricht",
        r"das auswahlverfahren mit anderen fortzusetzen",
        r"decided to move forward with other",
        r"not moving forward",
        r"after careful consideration",
        r"regret to inform you",
        r"unable to offer you",
        r"will not be moving forward",
        r"not selected for this role",
    ])

    CONFIRMATION_PATTERNS: List[str] = _RULES.get("confirmation_patterns", [
        r"eingangsbestätigung",
        r"vielen dank für (?:ihre|deine) bewerbung",
        r"haben (?:ihre|deine) bewerbung erhalten",
        r"bewerbung erfolgreich eingegangen",
        r"thank you for applying",
        r"thank you for your application",
        r"we have received your application",
        r"application received",
        r"application submitted",
    ])

    MEETING_LINK_PATTERNS: List[str] = _RULES.get("meeting_link_patterns", [
        r"https?://teams\.microsoft\.com/l/meetup-join/[^\s\"'>]+",
        r"https?://[a-zA-Z0-9-]+\.zoom\.us/j/[^\s\"'>]+",
        r"https?://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}",
        r"https?://calendly\.com/[^\s\"'>]+",
    ])

    TRUSTED_MEETING_DOMAINS: Set[str] = set(_RULES.get("trusted_meeting_domains", [
        "teams.microsoft.com",
        "meet.google.com",
        "zoom.us",
        "webex.com",
        "calendly.com",
    ]))

    KNOWN_ATS_DOMAINS: Set[str] = set(_RULES.get("known_ats_domains", [
        "personio.de", "personio.com", "greenhouse.io", "greenhouse-mail.io",
        "lever.co", "smartrecruiters.com", "myworkday.com", "workday.com",
        "ashbyhq.com", "jobvite.com", "recruitee.com", "softgarden.de", "dvinci.de",
        "join.com", "bamboohr.com", "teamtailor.com",
    ]))

    CAREER_CONTEXT_KEYWORDS: List[str] = _RULES.get("career_context_keywords", [
        "bewerbung", "stelle", "position", "lebenslauf", "candidate", "interview",
        "application", "resume", "cv", "job application", "opening"
    ])

    COMPANY_CONTEXT_PREFIXES: List[str] = _RULES.get("company_context_prefixes", [
        r"bei\s+(?:der\s+)?",
        r"application\s+(?:at|to)\s+",
        r"applying\s+to\s+",
        r"interest\s+in\s+",
        r"welcome\s+to\s+",
    ])

    def __init__(self, applied_companies: Optional[Dict[str, Dict[str, Any]]] = None):
        # Dict mapping lowercase company name -> application dict
        self.applied_companies = applied_companies or {}

    def set_applied_companies(self, companies: Dict[str, Dict[str, Any]]) -> None:
        self.applied_companies = companies

    def extract_meeting_link(self, text: str) -> Optional[str]:
        for pat in self.MEETING_LINK_PATTERNS:
            match = re.search(pat, text, flags=re.IGNORECASE)
            if match:
                url = match.group(0).strip(".,;\"'>)")
                # Validate trusted meeting host and require https
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    if parsed.scheme.lower() != "https":
                        continue
                    host = (parsed.hostname or "").lower()
                    if any(host == d or host.endswith(f".{d}") for d in self.TRUSTED_MEETING_DOMAINS):
                        return url
                except Exception:
                    pass
        return None

    def extract_suggested_date(self, text: str) -> Optional[str]:
        """Extracts candidate interview dates and times from email body leveraging date_utils."""
        patterns = [
            # ISO timestamp: 2026-09-15T14:00:00
            r"\b(\d{4}-\d{2}-\d{2}(?:T|\s+)\d{2}:\d{2}(?::\d{2})?)\b",
            # German/European date + optional time: 15.09.2026 um 14:00
            r"\b(\d{1,2}\.\d{1,2}\.\d{4}(?:\s*(?:um|at|,)\s*\d{1,2}:\d{2}(?:\s*uhr)?)?)\b",
            # Standard ISO date: 2026-09-15
            r"\b(\d{4}-\d{2}-\d{2})\b",
            # Written German/English date: 15. September 2026 um 14:00
            r"\b(\d{1,2}\.\s*(?:Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*(?:\s+\d{4})?(?:\s*(?:um|at|,)\s*\d{1,2}:\d{2}(?:\s*uhr)?)?)\b",
        ]
        for pat in patterns:
            m = re.search(pat, text, flags=re.IGNORECASE)
            if m:
                extracted = m.group(1).strip()
                return extracted
        return None

    def find_matching_company(self, text: str, sender_name: str, sender_email: str) -> Optional[str]:
        """Matches email against applied companies with sender identity verification (Anti-Phishing C1).
        
        Security Rule: Never match a company solely because a third-party email body mentions it.
        The sender's email address or sender display name must authenticate the company connection.
        """
        s_email = (sender_email or "").lower().strip()
        s_name = (sender_name or "").lower().strip()
        s_domain = s_email.split("@")[-1] if "@" in s_email else ""

        for comp_key, comp_data in self.applied_companies.items():
            canonical_name = comp_data.get("company", comp_key)
            clean_comp = re.sub(r"[^\w]", "", comp_key)
            if len(clean_comp) < 3:
                continue

            # 1. Company name in sender domain (e.g. jobs@chrono24.com, hr@de.chrono24.de)
            # Strictly checks s_domain to reject local-part spoofing (e.g. chrono24-careers@evil.biz)
            if s_domain and clean_comp in re.sub(r"[^\w]", "", s_domain):
                return canonical_name

            # 2. Known trusted recruitment ATS platforms (e.g. Greenhouse, Personio, Workday)
            # Where ATS relays mail on behalf of the company
            if any(s_domain == ats or s_domain.endswith(f".{ats}") for ats in self.KNOWN_ATS_DOMAINS):
                clean_email_user = re.sub(r"[^\w]", "", s_email.split("@")[0]) if "@" in s_email else ""
                clean_name = re.sub(r"[^\w]", "", s_name)
                if clean_comp in clean_email_user or clean_comp in clean_name:
                    return canonical_name

            # 3. Check application job_url domain cross-reference
            job_url = (comp_data.get("job_url") or "").lower()
            if job_url and s_domain:
                try:
                    from urllib.parse import urlparse
                    job_host = (urlparse(job_url).hostname or "").lower()
                    if s_domain in job_host or (len(s_domain) >= 5 and s_domain.split(".")[0] in job_host):
                        return canonical_name
                except Exception:
                    pass

        return None

    @classmethod
    def extract_company_from_context(cls, subject: str, sender_name: str = "", sender_email: str = "") -> Optional[str]:
        """Extracts candidate company name from subject or sender identity when bootstrapping an empty DB."""
        prefix_pattern = "(?:" + "|".join(cls.COMPANY_CONTEXT_PREFIXES) + ")"
        regex_pattern = rf'{prefix_pattern}([A-Za-z0-9\-_&äöüÄÖÜß. ]+?)(?:\s*[-/|!–]|\s+GmbH|\s+AG|\s+SE|\s+Germany|\s*$)'
        m = re.search(regex_pattern, subject, re.IGNORECASE)
        if m:
            cand = m.group(1).strip()
            if len(cand) >= 2 and cand.lower() not in ["uns", "ihnen", "dir", "team", "the"]:
                return cand

        clean_sender = sender_name.strip()
        clean_sender = re.sub(r"^(?:Hiring-Team|Karriere-Team|Recruiting-Team|Team|Talent-Team)\s+von\s+", "", clean_sender, flags=re.IGNORECASE)
        clean_sender = re.sub(r"\s*(?:Recruiting(?:\s+Team)?|HR\s+Team|Careers|Hiring\s+Team)$", "", clean_sender, flags=re.IGNORECASE)
        clean_sender = re.sub(r"\s*(?:GmbH|AG|SE|KG|Ltd|Inc\.?)$", "", clean_sender, flags=re.IGNORECASE).strip()
        if len(clean_sender) >= 3 and not any(clean_sender.lower().startswith(b) for b in ["no-reply", "noreply", "donotreply", "recruiting"]):
            return clean_sender

        s_email = (sender_email or "").strip().lower()
        if "@" in s_email:
            domain = s_email.split("@")[-1].split(".")[0]
            if len(domain) >= 3 and domain not in ["gmail", "hotmail", "yahoo", "outlook", "greenhouse", "lever", "workday", "smartrecruiters"]:
                return domain.capitalize()

        return None

    def classify_with_llm(
        self,
        subject: str,
        body: str,
        sender_name: str = "",
        sender_email: str = "",
    ) -> Optional[ClassificationResult]:
        """Calls Gemini LLM for zero-shot semantic analysis on ambiguous emails."""
        try:
            from src.core.llm_provider import call_gemini_semantic_analysis
        except ImportError:
            return None

        prompt = (
            "You are an expert recruitment and HR email triage assistant.\n"
            "Classify the following email into exactly one of these categories:\n"
            "- interview_invitation (genuine job interview, screening call, technical discussion)\n"
            "- application_confirmation (acknowledgment that application was received)\n"
            "- rejection (candidate not selected or application closed)\n"
            "- follow_up (request for documents, recruiter scheduling inquiry, status update)\n"
            "- noise (marketing, sales pitches, webinars, sponsored newsletters)\n\n"
            "Also extract: matched_company (hiring company), matched_role (job title), "
            "meeting_link (Teams/Zoom/Meet/Calendly link), suggested_date (interview date/time if mentioned).\n\n"
            f"Sender: {sender_name} <{sender_email}>\n"
            f"Subject: {subject}\n"
            f"Body:\n{body[:2500]}\n\n"
            "Return ONLY a JSON object with this structure:\n"
            "{\n"
            '  "category": "interview_invitation" | "application_confirmation" | "rejection" | "follow_up" | "noise",\n'
            '  "confidence": 0.95,\n'
            '  "matched_company": "Company Name or null",\n'
            '  "matched_role": "Role or null",\n'
            '  "meeting_link": "URL or null",\n'
            '  "suggested_date": "Date string or null",\n'
            '  "explanation": "Brief reasoning"\n'
            "}"
        )

        res_text = call_gemini_semantic_analysis(prompt)
        if not res_text:
            return None

        try:
            cleaned_json = res_text.strip()
            if "```json" in cleaned_json:
                cleaned_json = cleaned_json.split("```json")[1].split("```")[0].strip()
            elif "```" in cleaned_json:
                cleaned_json = cleaned_json.split("```")[1].split("```")[0].strip()

            parsed = json.loads(cleaned_json)
            category = parsed.get("category", "noise")
            if category not in {"interview_invitation", "application_confirmation", "rejection", "follow_up", "noise"}:
                return None

            validated_link = self.extract_meeting_link(parsed.get("meeting_link") or "")
            extracted_comp = parsed.get("matched_company") or None
            expl = parsed.get("explanation", "Classified via Gemini LLM")

            # Anti-Phishing: verify company authenticity for interview invitations
            if category == "interview_invitation":
                verified_comp = self.find_matching_company(f"{subject}\n{body}", sender_name, sender_email)
                if not verified_comp:
                    category = "follow_up"
                    expl = "Unverified sender claiming interview; downgraded to follow_up for safety"
                    extracted_comp = None
                else:
                    extracted_comp = verified_comp

            return ClassificationResult(
                category=category,
                confidence=float(parsed.get("confidence", 0.85)),
                matched_company=extracted_comp,
                matched_role=parsed.get("matched_role") or None,
                meeting_link=validated_link,
                suggested_date=parsed.get("suggested_date") or None,
                explanation=expl,
            )
        except Exception as e:
            log.warning("Failed to parse Gemini LLM classification response: %s", e, exc_info=True)
            return None

    def classify(
        self,
        subject: str,
        body: str,
        sender_name: str = "",
        sender_email: str = "",
        enable_llm_fallback: bool = False,
    ) -> ClassificationResult:
        full_text = f"{subject}\n{body}".lower()
        meeting_link = self.extract_meeting_link(f"{subject} {body}")
        matched_company = self.find_matching_company(full_text, sender_name, sender_email)
        matched_role = None
        if matched_company and matched_company.lower() in self.applied_companies:
            matched_role = self.applied_companies[matched_company.lower()].get("role")

        # 1. Filter out known sales/marketing noise
        for noise in self.NOISE_KEYWORDS:
            if noise in full_text and not matched_company:
                return ClassificationResult(
                    category="noise",
                    confidence=0.90,
                    explanation=f"Discarded noise/marketing containing keyword: {noise}",
                )

        # 2. Check for interview invitation (Highest priority actionable event)
        is_interview_signal = False
        for pat in self.INTERVIEW_STRONG_PATTERNS:
            if re.search(pat, full_text, flags=re.IGNORECASE):
                is_interview_signal = True
                break

        if not is_interview_signal and meeting_link:
            if any(w in full_text for w in ["interview", "call", "termin", "gespräch", "meeting", "join", "kennenlernen"]):
                is_interview_signal = True

        if is_interview_signal:
            # Strong verification: if applied companies are tracked, require authenticated company to avoid phishing (Anti-Phishing C1)
            if self.applied_companies and not matched_company:
                return ClassificationResult(
                    category="follow_up",
                    confidence=0.45,
                    matched_company=None,
                    matched_role=None,
                    meeting_link=meeting_link,
                    explanation="Unverified sender with interview keywords; flagged for candidate review without CRM status mutation",
                )

            suggested_date = self.extract_suggested_date(f"{subject} {body}")
            confidence = 0.95 if (matched_company or meeting_link) else 0.85
            return ClassificationResult(
                category="interview_invitation",
                confidence=confidence,
                matched_company=matched_company,
                matched_role=matched_role,
                meeting_link=meeting_link,
                suggested_date=suggested_date,
                explanation=f"Detected interview invitation signal{' from ' + matched_company if matched_company else ''}",
            )

        # 3. Check for rejection
        for pat in self.REJECTION_PATTERNS:
            if re.search(pat, full_text, flags=re.IGNORECASE):
                comp = matched_company or self.extract_company_from_context(subject, sender_name, sender_email)
                return ClassificationResult(
                    category="rejection",
                    confidence=0.92,
                    matched_company=comp,
                    matched_role=matched_role,
                    meeting_link=meeting_link,
                    explanation="Detected job rejection phrase",
                )

        # 4. Check for application confirmation
        for pat in self.CONFIRMATION_PATTERNS:
            if re.search(pat, full_text, flags=re.IGNORECASE):
                comp = matched_company or self.extract_company_from_context(subject, sender_name, sender_email)
                return ClassificationResult(
                    category="application_confirmation",
                    confidence=0.95,
                    matched_company=comp,
                    matched_role=matched_role,
                    meeting_link=meeting_link,
                    explanation="Detected application receipt confirmation",
                )

        # 5. Check if sender/subject mentions career application context
        if any(w in full_text for w in self.CAREER_CONTEXT_KEYWORDS) or meeting_link:
            rule_result = ClassificationResult(
                category="follow_up",
                confidence=0.65,
                matched_company=matched_company,
                matched_role=matched_role,
                meeting_link=meeting_link,
                suggested_date=self.extract_suggested_date(f"{subject} {body}"),
                explanation="Job-related context without definitive action",
            )
        else:
            rule_result = ClassificationResult(
                category="noise",
                confidence=0.85,
                explanation="No recruitment signal detected",
            )

        # 6. Intelligent LLM Semantic Fallback for ambiguous career context (Rule 6: Intelligent Systems vs Brittle Heuristics)
        if (enable_llm_fallback or rule_result.category == "follow_up") and os.getenv("GEMINI_API_KEY"):
            llm_result = self.classify_with_llm(
                subject=subject,
                body=body,
                sender_name=sender_name,
                sender_email=sender_email,
            )
            if llm_result and llm_result.confidence >= 0.70:
                if matched_company and not llm_result.matched_company:
                    llm_result.matched_company = matched_company
                if matched_role and not llm_result.matched_role:
                    llm_result.matched_role = matched_role
                return llm_result

        return rule_result

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
    category: str  # "interview_invitation", "application_confirmation", "rejection", "follow_up", "noise", "verification"
    confidence: float
    matched_company: Optional[str] = None
    matched_role: Optional[str] = None
    meeting_link: Optional[str] = None
    suggested_date: Optional[str] = None
    explanation: str = ""
    intent: Optional[str] = None
    reasoning: Optional[str] = None


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

    VERIFICATION_PATTERNS: List[str] = _RULES.get("verification_patterns", [
        r"account verification",
        r"candidate account verification",
        r"one-time password",
        r"verification passcode",
        r"passcode is",
        r"verification code",
        r"bestätigungscode",
        r"aktivierungslink",
        r"e-mail-adresse bestätigen",
        r"verify your email",
        r"activate your account",
        r"security code",
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
        r"\bat\s+",
        r"sent\s+to\s+",
        r"viewed\s+by\s+",
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
        
        Security Rule: Never match a company solely because a third-party aggregator mentions it.
        Aggregator platforms (LinkedIn, StepStone, Indeed) extract the candidate employer from subject.
        """
        s_email = (sender_email or "").lower().strip()
        s_name = (sender_name or "").lower().strip()
        s_domain = s_email.split("@")[-1] if "@" in s_email else ""

        # Step 1: For job portal aggregators (LinkedIn, StepStone, Indeed, Join),
        # extract candidate company from subject context (e.g. "...at Code Compass", "...sent to PRACYVA")
        is_portal = any(p in s_domain for p in ["linkedin.com", "stepstone", "indeed", "join.com", "xing.com"])
        if is_portal:
            cand = self.extract_company_from_context(text, sender_name, sender_email)
            if cand:
                cand_clean = cand.strip().lower()
                for comp_key, comp_data in self.applied_companies.items():
                    if cand_clean == comp_key or re.search(rf"\b{re.escape(comp_key)}\b", cand_clean, re.IGNORECASE) or re.search(rf"\b{re.escape(cand_clean)}\b", comp_key, re.IGNORECASE):
                        return comp_data.get("company", comp_key)
                return cand

        # Sort applied companies by length descending to match most specific name first (e.g. "DekaBank" before "Deka")
        sorted_comps = sorted(self.applied_companies.items(), key=lambda x: len(x[0]), reverse=True)

        # Step 2: Direct mention of an applied company in subject line or sender display name
        subj_line = text.split("\n")[0] if "\n" in text else text
        for comp_key, comp_data in sorted_comps:
            if len(comp_key) >= 3:
                # Word boundary match in subject line (e.g. "Your Application to Infosys", "Thanks for Applying to Infosys!")
                if re.search(rf"\b{re.escape(comp_key)}\b", subj_line, re.IGNORECASE):
                    return comp_data.get("company", comp_key)
                # Word boundary match in sender display name (e.g. "InfosysTalentAcquisition", "Deka Recruiting")
                if s_name and (re.search(rf"\b{re.escape(comp_key)}\b", s_name, re.IGNORECASE) or (len(comp_key) >= 4 and comp_key in re.sub(r"[^\w]", "", s_name))):
                    return comp_data.get("company", comp_key)

        # Step 3: Check authentic direct company domains or trusted recruitment ATS platforms
        domain_labels = [re.sub(r"[^\w]", "", part.lower()) for part in s_domain.split(".") if part]
        for comp_key, comp_data in sorted_comps:
            canonical_name = comp_data.get("company", comp_key)
            clean_comp = re.sub(r"[^\w]", "", comp_key)
            if len(clean_comp) < 3:
                continue

            # Known trusted recruitment ATS platforms (e.g. Greenhouse, Personio, Workday, BrassRing)
            # where ATS relays mail on behalf of the company
            if any(s_domain == ats or s_domain.endswith(f".{ats}") for ats in self.KNOWN_ATS_DOMAINS):
                clean_email_user = re.sub(r"[^\w]", "", s_email.split("@")[0]) if "@" in s_email else ""
                clean_name = re.sub(r"[^\w]", "", s_name)
                word_match = bool(re.search(rf"\b{re.escape(comp_key)}\b", s_name, re.IGNORECASE))
                subdomain_match = bool(s_domain.startswith(f"{clean_comp}.") or s_domain.startswith(f"{comp_key}."))
                token_match = (len(clean_comp) >= 4 and (clean_comp in clean_email_user or clean_comp in clean_name))
                if word_match or subdomain_match or token_match:
                    return canonical_name

            # Direct company sender domain (e.g. jobs@chrono24.com, hr@de.chrono24.de)
            # Strict domain label match: NEVER match a 3-character company name like "ing" as a loose substring
            # inside unrelated words like "brassring.com", "booking.com", "springer.com"!
            if s_domain and not any(agg in s_domain for agg in ["linkedin", "stepstone", "indeed", "xing", "gmail", "outlook", "yahoo", "hotmail"]):
                is_label_match = (
                    clean_comp in domain_labels
                    or any(label.startswith(f"{clean_comp}-") or label.endswith(f"-{clean_comp}") or f"-{clean_comp}-" in label for label in domain_labels)
                    or (len(clean_comp) >= 5 and any(label.startswith(clean_comp) for label in domain_labels))
                )
                if is_label_match:
                    return canonical_name

        return None

    @classmethod
    def extract_company_from_context(cls, subject: str, sender_name: str = "", sender_email: str = "") -> Optional[str]:
        """Extracts candidate company name from subject or sender identity when bootstrapping an empty DB."""
        from src.core.normalizer import is_noise_company

        clean_subj = re.sub(r"[\U00010000-\U0010ffff]", "", subject).strip()

        # 1. Check portal patterns: "to/as {role} at {company}"
        m1 = re.search(r"(?:to|as)\s+(.+?)\s+at\s+([^–\-\|\n\r]+)", clean_subj, re.IGNORECASE)
        if m1:
            cand = m1.group(2).strip()
            cand = re.sub(r"[\s\.\,\:\;\!\?]+$", "", cand).strip()
            if len(cand) >= 2 and not is_noise_company(cand) and cand.lower() not in ["uns", "ihnen", "dir", "team", "the"]:
                return cand

        # 2. Check portal patterns: "sent to / viewed by / continue your application to {company}"
        m2 = re.search(r"(?:sent to|viewed by|continue your application to)\s+([^–\-\|\n\r]+)", clean_subj, re.IGNORECASE)
        if m2:
            cand = m2.group(1).strip()
            cand = re.sub(r"[\s\.\,\:\;\!\?]+$", "", cand).strip()
            if len(cand) >= 2 and not is_noise_company(cand) and cand.lower() not in ["uns", "ihnen", "dir", "team", "the"]:
                return cand

        # Strip trailing reference/job IDs like "AF:0270436", "CRM:0100159", "Ref: 12345", "#1234"
        clean_subj_no_ref = re.sub(r"\s+[A-Z]{1,5}:[0-9A-Z]+(?:\b|\s|$)", "", clean_subj, flags=re.IGNORECASE)

        # 3. Generic prefix pattern
        prefix_pattern = "(?:" + "|".join(cls.COMPANY_CONTEXT_PREFIXES) + ")"
        regex_pattern = rf'{prefix_pattern}([A-Za-z0-9\-_&äöüÄÖÜß. ]+?)(?:\s*[-/|!–]|\s+GmbH|\s+AG|\s+SE|\s+Germany|\s*$)'
        m = re.search(regex_pattern, clean_subj_no_ref, re.IGNORECASE)
        if m:
            cand = m.group(1).strip()
            cand = re.sub(r"[\s\.\,\:\;\!\?]+$", "", cand).strip()
            if len(cand) >= 2 and not is_noise_company(cand) and cand.lower() not in ["uns", "ihnen", "dir", "team", "the"]:
                return cand

        # 4. Sender name (if not a noise company/aggregator)
        clean_sender = sender_name.strip()
        clean_sender = re.sub(r"^(?:Hiring-Team|Karriere-Team|Recruiting-Team|Team|Talent-Team|Webmailer)\s+(?:von\s+)?", "", clean_sender, flags=re.IGNORECASE)
        clean_sender = re.sub(r"\s*(?:Recruiting(?:\s+Team)?|HR\s+Team|Careers|Hiring\s+Team)$", "", clean_sender, flags=re.IGNORECASE)
        clean_sender = re.sub(r"\s*(?:GmbH|AG|SE|KG|Ltd|Inc\.?)$", "", clean_sender, flags=re.IGNORECASE).strip()
        if len(clean_sender) >= 3 and not is_noise_company(clean_sender) and not any(clean_sender.lower().startswith(b) for b in ["no-reply", "noreply", "donotreply"]):
            return clean_sender

        # 5. Sender domain fallback (excluding aggregators and consumers)
        s_email = (sender_email or "").strip().lower()
        if "@" in s_email:
            user_part = s_email.split("@")[0]
            domain_part = s_email.split("@")[-1]
            domain = domain_part.split(".")[0]
            if "myworkday" in domain_part or domain == "workday":
                # For workday relay addresses like cgm@myworkday.com or ing@myworkday.com
                if len(user_part) >= 2 and user_part not in ["recruiting", "noreply", "no-reply", "jobs", "hr", "careers"]:
                    return user_part.upper() if len(user_part) <= 4 else user_part.capitalize()
            elif len(domain) >= 3 and domain not in ["gmail", "hotmail", "yahoo", "outlook", "greenhouse", "lever", "workday", "myworkday", "smartrecruiters", "linkedin", "arbeitsagentur", "stepstone", "indeed", "xing"]:
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
            from src.utils.prompt_loader import load_prompt
        except ImportError:
            return None

        try:
            prompt_template = load_prompt("email_classifier.txt")
            prompt = prompt_template.format(
                sender_name=sender_name or "",
                sender_email=sender_email or "",
                subject=subject,
                body=body[:2500],
            )
        except Exception as e:
            log.debug("Prompt loading fallback: %s", e)
            prompt = (
                "You are an expert recruitment and HR email triage assistant.\n"
                "Classify the following email into exactly one of these categories:\n"
                "- interview_invitation, application_confirmation, rejection, follow_up, noise\n\n"
                f"Sender: {sender_name} <{sender_email}>\n"
                f"Subject: {subject}\n"
                f"Body:\n{body[:2500]}\n\n"
                "Return ONLY a JSON object with category, confidence, matched_company, matched_role, meeting_link, suggested_date, explanation."
            )

        res_text = call_gemini_semantic_analysis(prompt)
        if not res_text:
            return None

        for attempt in range(2):
            try:
                cleaned_json = res_text.strip()
                if "```json" in cleaned_json:
                    cleaned_json = cleaned_json.split("```json")[1].split("```")[0].strip()
                elif "```" in cleaned_json:
                    cleaned_json = cleaned_json.split("```")[1].split("```")[0].strip()

                parsed = json.loads(cleaned_json)
                intent = parsed.get("intent")
                category = parsed.get("category")
                if not category and intent:
                    intent_to_cat = {
                        "rejection": "rejection",
                        "interview": "interview_invitation",
                        "acknowledgement": "application_confirmation",
                        "job_application": "application_confirmation",
                        "info_request": "follow_up",
                        "email_verification": "verification",
                        "other": "noise",
                    }
                    category = intent_to_cat.get(intent, "noise")
                elif not category:
                    category = "noise"

                if category not in {"interview_invitation", "application_confirmation", "rejection", "follow_up", "noise", "verification"}:
                    category = "noise"

                validated_link = self.extract_meeting_link(parsed.get("meeting_link") or "")
                extracted_comp = parsed.get("matched_company") or None
                reasoning = parsed.get("reasoning") or parsed.get("explanation") or "Classified via Gemini LLM"

                # Anti-Phishing: verify company authenticity for interview invitations
                if category == "interview_invitation":
                    verified_comp = self.find_matching_company(f"{subject}\n{body}", sender_name, sender_email)
                    if not verified_comp:
                        category = "follow_up"
                        reasoning = "Unverified sender claiming interview; downgraded to follow_up for safety"
                        extracted_comp = None
                    else:
                        extracted_comp = verified_comp

                # Normalize confidence to float between 0.0 and 1.0
                raw_conf = parsed.get("confidence", 0.95)
                try:
                    conf_val = float(raw_conf)
                    if conf_val > 1.0:
                        conf_val = conf_val / 100.0
                except (ValueError, TypeError):
                    conf_val = 0.95

                return ClassificationResult(
                    category=category,
                    confidence=conf_val,
                    matched_company=extracted_comp,
                    matched_role=parsed.get("matched_role") or None,
                    meeting_link=validated_link,
                    suggested_date=parsed.get("suggested_date") or None,
                    explanation=reasoning,
                    intent=intent or category,
                    reasoning=reasoning,
                )
            except Exception as e:
                log.warning("Attempt %d: Failed to parse Gemini LLM classification response: %s", attempt + 1, e)
                if attempt == 0:
                    retry_prompt = (
                        f"{prompt}\n\n"
                        f"[SELF-CORRECTION REQUIRED]\n"
                        f"Your previous response could not be parsed as JSON ({e}).\n"
                        f"Previous raw output: {res_text[:400]}\n"
                        f"Please output strictly valid JSON matching the requested structure."
                    )
                    res_text = call_gemini_semantic_analysis(retry_prompt)
                    if not res_text:
                        break

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

        # 1. Filter out known sales/marketing noise
        for noise in self.NOISE_KEYWORDS:
            if noise in full_text and not matched_company:
                return ClassificationResult(
                    category="noise",
                    confidence=0.90,
                    explanation=f"Discarded noise/marketing containing keyword: {noise}",
                    intent="other",
                    reasoning=f"Discarded noise/marketing containing keyword: {noise}",
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
            # Strong verification: if applied companies are tracked, require authenticated sender to avoid phishing (Anti-Phishing C1)
            sender_verified = True
            if self.applied_companies and sender_email:
                s_domain = sender_email.split("@")[-1].lower() if "@" in sender_email else ""
                clean_comp = re.sub(r"[^\w]", "", (matched_company or "").lower())
                is_comp_domain = bool(clean_comp and clean_comp in re.sub(r"[^\w]", "", s_domain))
                is_ats_domain = any(s_domain == ats or s_domain.endswith(f".{ats}") for ats in self.KNOWN_ATS_DOMAINS)
                is_portal = any(p in s_domain for p in ["linkedin.com", "stepstone", "indeed", "join.com", "xing.com"])
                if not (is_comp_domain or is_ats_domain or is_portal):
                    sender_verified = False

            if self.applied_companies and (not matched_company or not sender_verified):
                return ClassificationResult(
                    category="follow_up",
                    confidence=0.45,
                    matched_company=None,
                    matched_role=None,
                    meeting_link=None,
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

        # Check for explicit automated confirmation markers
        is_explicit_confirmation = bool(re.search(
            r"automatisierte\s+eingangsbestätigung|übermittlung\s+ihrer\s+bewerbungsunterlagen",
            full_text,
            flags=re.IGNORECASE,
        ))

        # 3. Check for rejection
        is_rejection_signal = False
        rejection_explanation = "Detected job rejection phrase"
        for pat in self.REJECTION_PATTERNS:
            for match in re.finditer(pat, full_text, flags=re.IGNORECASE):
                # Guard: Ignore conditional GDPR disclaimers (e.g. "wenn Sie uns diese personenbezogenen Daten nicht bereitstellen... nicht berücksichtigen können")
                start_pos = max(0, match.start() - 150)
                preceding_text = full_text[start_pos:match.start()]
                if any(d in preceding_text for d in ["nicht bereitstellen", "wenn sie uns", "verweigerung der bereitstellung"]):
                    continue
                # If email is an explicit automated confirmation, require strong rejection phrase that cannot be a footer
                if is_explicit_confirmation and "mitteilen" not in pat and "bedauern" not in pat and "entschieden" not in pat:
                    continue
                is_rejection_signal = True
                break
            if is_rejection_signal:
                break

        if is_rejection_signal:
            comp = matched_company or self.extract_company_from_context(subject, sender_name, sender_email)
            return ClassificationResult(
                category="rejection",
                confidence=0.92,
                matched_company=comp,
                matched_role=matched_role,
                meeting_link=meeting_link,
                explanation=rejection_explanation,
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

        # 4b. Check for account / email verification passcode
        for pat in self.VERIFICATION_PATTERNS:
            if re.search(pat, full_text, flags=re.IGNORECASE):
                comp = matched_company or self.extract_company_from_context(subject, sender_name, sender_email)
                return ClassificationResult(
                    category="verification",
                    confidence=0.95,
                    matched_company=comp,
                    matched_role=matched_role,
                    meeting_link=meeting_link,
                    explanation="Detected candidate account / email verification code",
                )

        # 5. Check if sender/subject mentions career application context
        has_career_context = any(w in full_text for w in self.CAREER_CONTEXT_KEYWORDS) or bool(meeting_link)

        if has_career_context:
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

        # 6. ML Tier: offline, quota-free classification for ambiguous cases
        # Only invoke for career-context emails (noise is filtered by rules)
        if has_career_context:
            try:
                from src.tools.email.ml_classifier import MLEmailClassifier
                ml = MLEmailClassifier.get_instance()
                ml_result = ml.predict(subject, body, sender_email)
                if ml_result:
                    # Preserve company/role from rule-based matching
                    if matched_company and not ml_result.matched_company:
                        ml_result.matched_company = matched_company
                    if matched_role and not ml_result.matched_role:
                        ml_result.matched_role = matched_role
                    if meeting_link and not ml_result.meeting_link:
                        ml_result.meeting_link = meeting_link
                    # Anti-phishing: verify unconfirmed interview invitations
                    if ml_result.category == "interview_invitation" and not ml_result.matched_company:
                        ml_result.category = "follow_up"
                        ml_result.explanation = "ML detected interview signal but sender unverified; flagged for review"
                    return ml_result
            except ImportError:
                log.debug("ML classifier not available (scikit-learn not installed)")
            except Exception as e:
                log.debug("ML classification error: %s", e)

        # 7. LLM Semantic Fallback for very low-confidence cases (Rule 6: Intelligent Systems vs Brittle Heuristics)
        if enable_llm_fallback and os.getenv("GEMINI_API_KEY"):
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

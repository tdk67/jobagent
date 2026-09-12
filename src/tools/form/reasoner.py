"""Whole-form semantic reasoning engine powered by Google Gemini and persistent QA memory.

Implements clean-code guidelines:
- Zero brittle regex explosions: handles infinite linguistic and portal variations in English and German.
- Continuous learning: newly resolved screening answers are automatically persisted in QA memory.
- Multimodal/semantic reasoning over form structure, dropdowns, and candidate profile context.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from src.core.config import AppConfig, load_config
from src.core.llm_provider import call_gemini_semantic_analysis
from src.core.profile import CandidateProfile, load_profile
from src.core.storage import JobAgentStorage

log = logging.getLogger(__name__)


class FormReasoner:
    """Orchestrates candidate profile mapping, QA memory retrieval, and Gemini whole-form reasoning."""

    def __init__(
        self,
        storage: Optional[JobAgentStorage] = None,
        profile: Optional[CandidateProfile] = None,
        config: Optional[AppConfig] = None,
    ):
        self.config = config or load_config()
        self.storage = storage or JobAgentStorage(self.config.storage.database_path)
        self.profile = profile or load_profile()
        self._seeded = False

    def ensure_qa_seeded(self) -> None:
        """Lazily seeds QA memory with profile answers if not already done (avoids __init__ side-effects)."""
        if not self._seeded:
            self.storage.seed_qa_from_profile(self.profile)
            self._seeded = True

    def _match_core_profile(self, field: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Fast-path deterministic resolution for standard contact & personal fields."""
        label = (field.get("label") or "").strip().lower()
        name = (field.get("name") or "").strip().lower()
        field_id = (field.get("id") or "").strip().lower()
        placeholder = (field.get("placeholder") or "").strip().lower()
        tag_type = (field.get("type") or "").strip().lower()

        combined = f"{label} {name} {field_id} {placeholder}".lower()
        pers = self.profile.personal
        prefs = self.profile.preferences

        # 0. Middle Name / Zweiter Vorname (MUST be evaluated before First Name)
        if any(term in combined for term in ["middle name", "middlename", "zweiter vorname", "zweiter name", "weitere vornamen"]):
            middle_name = pers.middleName or ""
            return {"value": middle_name, "confidence": 1.0, "reasoning": "Candidate middle name (empty if none)"}

        # 1. First Name
        if any(term in combined for term in ["first name", "firstname", "vorname", "given name"]) and not any(
            skip in combined for skip in ["zweiter", "middle", "weitere"]
        ):
            first_name = pers.fullName.split()[0] if pers.fullName else ""
            return {"value": first_name, "confidence": 1.0, "reasoning": "Core profile first name"}

        # 2. Last Name
        if any(term in combined for term in ["last name", "lastname", "nachname", "familienname", "surname"]):
            parts = pers.fullName.split() if pers.fullName else []
            last_name = " ".join(parts[1:]) if len(parts) > 1 else (parts[0] if parts else "")
            return {"value": last_name, "confidence": 1.0, "reasoning": "Core profile last name"}

        # 3. Full Name
        if any(term in combined for term in ["full name", "fullname", "name", "ihr name"]) and not any(
            skip in combined for skip in ["company", "file", "user", "first", "last", "vorname", "nachname", "zweiter", "middle"]
        ):
            return {"value": pers.fullName, "confidence": 1.0, "reasoning": "Core profile full name"}

        # 4. Email
        if any(term in combined for term in ["email", "e-mail", "mail address", "e-mail-adresse"]) or tag_type == "email":
            return {"value": pers.email, "confidence": 1.0, "reasoning": "Core profile email"}

        # 5. Phone
        if any(term in combined for term in ["phone", "telefon", "mobile", "handy", "rufnummer", "contact number"]) or tag_type == "tel":
            return {"value": pers.phone, "confidence": 1.0, "reasoning": "Core profile phone"}

        # 5a. Phone country code / dialing prefix (e.g. "Länder-/Regionsvorwahl", "Country Code")
        # Must come AFTER the phone check to avoid false-positives on plain "Telefon" labels.
        if any(term in combined for term in [
            "länder", "regionsvorwahl", "vorwahl", "country code", "dialing code",
            "phone code", "country prefix", "area code",
        ]) and pers.phoneCountryCode:
            return {"value": pers.phoneCountryCode, "confidence": 1.0, "reasoning": "Core profile phone country code"}

        # 6. Preferred Job Location / Standort (Not residential street)
        if any(term in combined for term in ["welchen standort", "bevorzugter standort", "gewünschter standort", "target location", "primary location"]) or (
            "standort" in combined and any(k in combined for k in ["bewerben", "primär", "bevorzugt", "arbeiten", "wunsch"])
        ):
            target_loc = prefs.locations[0] if (prefs.locations and len(prefs.locations) > 0) else pers.city
            if target_loc:
                return {"value": target_loc, "confidence": 0.98, "reasoning": "Target job location preference from profile configuration"}

        # 7. City / Residence City
        if any(term in combined for term in ["city", "ort", "stadt", "wohnort", "residence city"]):
            city = pers.city or self._extract_city_from_address(pers.address)
            if city:
                return {"value": city, "confidence": 1.0, "reasoning": "Core profile city"}

        # 8. Country of Residence
        if any(term in combined for term in ["land des aktuellen wohnsitzes", "aktuellen wohnsitz", "wohnsitzland", "country of residence", "residence country"]):
            country = pers.countryDe or pers.countryEn
            if country:
                return {"value": country, "confidence": 1.0, "reasoning": "Configured country of residence"}

        if any(term in combined for term in ["address", "anschrift", "adresse", "street", "strasse"]) and not any(k in combined for k in ["email", "e-mail", "mail"]):
            return {"value": pers.address, "confidence": 1.0, "reasoning": "Core profile address"}

        # 9. Language Proficiency (Dynamically derived from candidate's profile configuration - zero hardcoded levels)
        for lang_name, lang_level in (self.profile.languages or {}).items():
            if not lang_level:
                continue
            norm_lang = lang_name.lower().strip()
            aliases = [norm_lang]
            if norm_lang in ("german", "deutsch"):
                aliases.extend(["deutsch", "german", "deutschkenntnisse"])
            elif norm_lang in ("english", "englisch"):
                aliases.extend(["englisch", "english", "englischkenntnisse"])
            elif norm_lang in ("french", "französisch", "franzosisch"):
                aliases.extend(["französisch", "franzosisch", "french"])
            elif norm_lang in ("spanish", "spanisch"):
                aliases.extend(["spanisch", "spanish"])
            elif norm_lang in ("italian", "italienisch"):
                aliases.extend(["italienisch", "italian"])

            if any(alias in combined for alias in aliases) and any(
                k in combined for k in ["kenntnis", "sprach", "level", "proficiency", "wie gut", "niveau", "skills"]
            ):
                return {"value": str(lang_level), "confidence": 1.0, "reasoning": f"Profile configured language proficiency for {lang_name}"}

        # 10. Work Authorization / Legal Right to Work
        if any(term in combined for term in ["arbeitserlaubnis", "work authorization", "work permit", "legal right to work", "erlaubnis in dem land"]):
            auth_val = pers.workAuthorizationDe or pers.workAuthorizationEn or "Ja"
            return {"value": auth_val, "confidence": 1.0, "reasoning": "Configured work authorization status"}

        # 11. Prior Employment at Target Company
        if (
            any(term in combined for term in ["bereits angestellt", "previously employed", "bereits gearbeitet", "früher beschäftigt", "früher angestellt"])
            or (("bereits" in combined or "früher" in combined or "previously" in combined) and ("angestellt" in combined or "beschäftigt" in combined or "employed" in combined or "gearbeitet" in combined))
        ):
            return {"value": "Nein", "confidence": 1.0, "reasoning": "No prior employment with company"}

        # 12. LinkedIn
        if "linkedin" in combined and pers.linkedinUrl:
            return {"value": pers.linkedinUrl, "confidence": 1.0, "reasoning": "Core profile LinkedIn URL"}

        # 13. GitHub / Portfolio
        if any(term in combined for term in ["github", "portfolio", "git url"]) and pers.githubUrl:
            return {"value": pers.githubUrl, "confidence": 1.0, "reasoning": "Core profile GitHub URL"}

        # 14. Salary Expectation
        if any(term in combined for term in ["salary", "gehalt", "gehaltserwartung", "compensation", "vergütung"]):
            return {"value": pers.salaryExpectation, "confidence": 0.95, "reasoning": "Core profile salary expectation"}

        # 15. Notice Period / Availability
        if any(term in combined for term in ["notice period", "kündigungsfrist", "availability", "verfügbarkeit", "eintrittstermin"]):
            return {"value": pers.noticePeriod, "confidence": 0.95, "reasoning": "Core profile notice period"}

        # 16. Citizenship
        if any(term in combined for term in ["citizenship", "staatsangehörigkeit", "visa", "nationalität"]):
            return {"value": pers.citizenship, "confidence": 0.95, "reasoning": "Core profile citizenship & authorization"}

        # 17. Preferred Work Model
        if any(term in combined for term in ["work model", "arbeitsmodell", "remote", "hybrid"]):
            return {"value": prefs.workModel, "confidence": 0.90, "reasoning": "Core profile work model preference"}

        # 18. Job Alerts / Notifications
        if any(term in combined for term in ["job alert", "job-angebot", "benachrichtigungen über", "benachrichtigungen ueber"]):
            return {"value": "true", "confidence": 1.0, "reasoning": "Job alert notification opt-in"}

        # 19. Privacy Policy / Data Protection Consent
        if any(term in combined for term in ["datenschutzerklärung", "datenschutzerklaerung", "datenschutz", "privacy policy"]):
            return {"value": "true", "confidence": 1.0, "reasoning": "Privacy policy consent"}

        # 20. Professional Headline / Title (common in LinkedIn Easy Apply)
        if any(term in combined for term in ["headline", "berufsbezeichnung", "professional headline", "profil-slogan", "kurztitel"]):
            headline_val = pers.headline or (prefs.targetRoles[0] if prefs.targetRoles else "")
            return {"value": headline_val, "confidence": 0.98, "reasoning": "Candidate professional headline"}

        # 21. Summary / Bio / About Me (common in LinkedIn Easy Apply textarea)
        if any(term in combined for term in ["summary", "zusammenfassung", "profilzusammenfassung", "über mich", "ueber mich", "about me", "professional summary", "kurzprofil"]):
            is_german = any(term in combined for term in ["zusammenfassung", "über mich", "ueber mich", "kurzprofil"])
            summary_val = (pers.summaryDe if is_german else (pers.summaryEn or pers.summaryDe)) or pers.summaryDe or pers.summaryEn
            if summary_val:
                return {"value": summary_val, "confidence": 0.98, "reasoning": "Candidate profile summary"}

        # 22. Text Cover Letter / Motivation / Essay (when presented as textarea or text input)
        if any(term in combined for term in ["cover letter", "coverletter", "anschreiben", "motivationsschreiben", "motivation", "warum bewerben"]):
            is_german = any(term in combined for term in ["anschreiben", "motivationsschreiben", "warum bewerben"])
            cover_val = (pers.coverLetterDe if is_german else (pers.coverLetterEn or pers.coverLetterDe)) or pers.coverLetterDe or pers.coverLetterEn
            if cover_val:
                return {"value": cover_val, "confidence": 0.98, "reasoning": "Candidate default cover letter / motivation text"}

        return None

    def _extract_city_from_address(self, address: Optional[str]) -> str:
        """Best-effort city extraction from an address string.

        Prefers an explicit postal-code-bearing segment (e.g. '60311 Frankfurt am Main')
        and strips the leading postal code if present. Never assumes the first comma
        segment is the city (that is usually the street).
        """
        if not address:
            return ""
        segments = [s.strip() for s in address.split(",") if s.strip()]
        if not segments:
            return ""
        postal = re.search(r"\b\d{4,5}\b", address)
        for seg in segments:
            if postal and postal.group(0) in seg:
                # Drop a leading postal code, keep the rest of the segment as the city
                candidate = re.sub(r"^\s*\d{4,5}\s*", "", seg).strip()
                return candidate or seg
        # No postal code: the last segment is the city for 'Street, City' layouts
        return segments[-1]

    LEGALLY_SENSITIVE_KEYWORDS = [
        "citizenship", "staatsangehörigkeit", "sponsorship", "visum", "visa",
        "arbeitserlaubnis", "work authorization", "criminal", "vorstrafen",
        "disability", "behinderung", "salary", "gehalt", "compensation"
    ]

    def reason_form(self, fields: List[Dict[str, Any]], page_url: Optional[str] = None) -> Dict[str, Any]:
        """Maps form fields using 2-pass strategy: Local Heuristics & QA Memory -> Multimodal Gemini 3.8 Flash."""
        self.ensure_qa_seeded()
        approved_mappings: Dict[str, Any] = {}
        unmapped_fields: List[Dict[str, Any]] = []
        reasonings: Dict[str, str] = {}
        requires_confirmation: List[str] = []

        # ---------------------------------------------------------------------
        # Pass 1: Local Deterministic Matching & Verified QA Memory Lookup
        # ---------------------------------------------------------------------
        for field in fields:
            fid = field.get("fieldId") or field.get("id") or field.get("name")
            if not fid:
                continue

            # Security: Never autofill password fields
            if str(field.get("type", "")).lower() == "password":
                continue

            core_match = self._match_core_profile(field)
            if core_match:
                val = core_match["value"]
                # Handle select dropdown option resolution
                if field.get("type") in ("select-one", "select", "radio") and field.get("options"):
                    selected_val = self._resolve_option_selection(str(val), field.get("options", []))
                    if selected_val is not None:
                        approved_mappings[fid] = selected_val
                        reasonings[fid] = f"Direct profile mapping to option '{selected_val}'"
                        continue

                approved_mappings[fid] = val
                reasonings[fid] = core_match.get("reasoning", "Direct profile attribute match")
                continue

            # Check persistent verified QA Memory
            q_text = field.get("label") or field.get("placeholder") or field.get("name")
            if q_text and len(q_text.strip()) >= 3:
                known_ans = self.storage.get_qa_answer(q_text)
                if known_ans is not None:
                    if field.get("type") in ("select-one", "select", "radio") and field.get("options"):
                        selected_val = self._resolve_option_selection(str(known_ans), field.get("options", []))
                        if selected_val is not None:
                            approved_mappings[fid] = selected_val
                            reasonings[fid] = f"Verified QA Memory resolved to option '{selected_val}'"
                            continue

                    approved_mappings[fid] = known_ans
                    reasonings[fid] = "Verified QA Memory match"
                    continue

            # Field remains unmapped
            unmapped_fields.append(field)

        # ---------------------------------------------------------------------
        # Pass 2: Multimodal Gemini 3.8 Flash Semantic Reasoning
        # ---------------------------------------------------------------------
        if unmapped_fields and os.getenv("GEMINI_API_KEY"):
            llm_results = self._reason_with_gemini(unmapped_fields, page_url)
            for fid, result in llm_results.items():
                val = result.get("value")
                if val is not None and val != "":
                    orig_field = next((x for x in unmapped_fields if (x.get("fieldId") or x.get("id") or x.get("name")) == fid), None)
                    # Resolve options for select/radio fields if necessary
                    if orig_field and orig_field.get("type") in ("select-one", "select", "radio") and orig_field.get("options"):
                        resolved_opt = self._resolve_option_selection(str(val), orig_field.get("options", []))
                        if resolved_opt is not None:
                            val = resolved_opt

                    approved_mappings[fid] = val
                    reasonings[fid] = result.get("reasoning", "Deduced via Gemini 3.8 Flash")

                    # Provenance Tracking: Store suggestions with verified=0 (C3: No self-certification)
                    confidence = float(result.get("confidence", 0.0))
                    if confidence >= 0.85:
                        q_text = orig_field.get("label") or orig_field.get("placeholder") or fid if orig_field else fid
                        if q_text and len(q_text.strip()) >= 3:
                            self.storage.save_qa_answer(
                                question_text=q_text,
                                answer=str(val),
                                category="llm_suggested",
                                verified=0,
                                provenance="llm_suggested",
                            )
                            log.info("Continuous Learning: Recorded unverified suggestion for '%s' (quarantined until user confirms)", q_text)

        # Identify fields requiring explicit human review (legally significant fields)
        for field in fields:
            fid = field.get("fieldId") or field.get("id") or field.get("name")
            if fid in approved_mappings:
                combined_desc = f"{field.get('label', '')} {field.get('name', '')}".lower()
                if any(kw in combined_desc for kw in self.LEGALLY_SENSITIVE_KEYWORDS):
                    requires_confirmation.append(fid)

        return {
            "mappings": approved_mappings,
            "total_fields": len(fields),
            "mapped_fields": len(approved_mappings),
            "reasonings": reasonings,
            "requires_confirmation": requires_confirmation,
        }

    def _resolve_option_selection(self, answer: str, options: List[Any]) -> Optional[Any]:
        """Matches a target answer string to the best dropdown option value or text."""
        if not options or not answer:
            return None
        ans_clean = str(answer).lower().strip()

        # 0. CEFR Language Level matching (A1, A2, B1, B2, C1, C2)
        cefr_match = re.search(r"\b([abc][12])\b", ans_clean, re.IGNORECASE)
        if cefr_match:
            target_cefr = cefr_match.group(1).lower()
            for opt in options:
                txt = (opt.get("text", "") if isinstance(opt, dict) else str(opt)).lower()
                val = (opt.get("value", "") if isinstance(opt, dict) else str(opt)).lower()
                opt_cefrs = [c.lower() for c in re.findall(r"\b([abc][12])\b", f"{txt} {val}", re.IGNORECASE)]
                if target_cefr in opt_cefrs:
                    return opt.get("value") if isinstance(opt, dict) and opt.get("value") is not None else (opt.get("text") if isinstance(opt, dict) else opt)

        # Filter out placeholder prompt options like "Keine Auswahl", "Select", "Bitte wählen".
        # Detection is intentionally text-only: some portals (e.g. SAP SuccessFactors) use
        # non-empty, non-numeric option values (GUIDs, "NONDISCLOSURE") for placeholders,
        # so inspecting optVal alone is not sufficient.
        _PLACEHOLDER_RE = re.compile(
            r"^(keine.*auswahl|bitte.*wählen|bitte.*wähle|please.*select|select\.{0,3}$|choose\.{0,3}$|---)",
            re.IGNORECASE,
        )
        candidate_opts = [
            opt for opt in options
            if not _PLACEHOLDER_RE.match(
                (opt.get("text", "") if isinstance(opt, dict) else str(opt)).lower().strip()
            )
        ]

        if not candidate_opts:
            candidate_opts = options

        # 1. Direct or substring match
        for opt in candidate_opts:
            val = (opt.get("value", "") if isinstance(opt, dict) else str(opt)).lower().strip()
            txt = (opt.get("text", "") if isinstance(opt, dict) else str(opt)).lower().strip()
            if ans_clean == val or ans_clean == txt:
                return opt.get("value") if isinstance(opt, dict) and opt.get("value") is not None else (opt.get("text") if isinstance(opt, dict) else opt)
            if ans_clean and (ans_clean in val or ans_clean in txt):
                return opt.get("value") if isinstance(opt, dict) and opt.get("value") is not None else (opt.get("text") if isinstance(opt, dict) else opt)
            if val and val in ans_clean:
                return opt.get("value") if isinstance(opt, dict) and opt.get("value") is not None else (opt.get("text") if isinstance(opt, dict) else opt)
            if txt and txt in ans_clean:
                return opt.get("value") if isinstance(opt, dict) and opt.get("value") is not None else (opt.get("text") if isinstance(opt, dict) else opt)

        # 2. Semantic matching for yes/no / authorization
        is_yes = any(y in ans_clean for y in ["yes", "ja", "eu", "citizen", "unrestricted", "uneingeschränkt", "full", "true"])
        is_no = any(n in ans_clean for n in ["no", "nein", "keine", "erforderlich", "false"])
        if is_yes and not is_no:
            for opt in candidate_opts:
                txt = (opt.get("text", "") if isinstance(opt, dict) else str(opt)).lower()
                val = (opt.get("value", "") if isinstance(opt, dict) else str(opt)).lower()
                if any(y in txt or y in val for y in ["ja", "yes", "true", "t", "uneingeschränkt", "vorhanden", "authorized"]):
                    return opt.get("value") if isinstance(opt, dict) and opt.get("value") is not None else (opt.get("text") if isinstance(opt, dict) else opt)
        elif is_no and not is_yes:
            for opt in candidate_opts:
                txt = (opt.get("text", "") if isinstance(opt, dict) else str(opt)).lower()
                val = (opt.get("value", "") if isinstance(opt, dict) else str(opt)).lower()
                if any(n in txt or n in val for n in ["nein", "no", "false", "f"]) and "auswahl" not in txt:
                    return opt.get("value") if isinstance(opt, dict) and opt.get("value") is not None else (opt.get("text") if isinstance(opt, dict) else opt)

        # 3. Country matching (Germany / Deutschland)
        if any(g in ans_clean for g in ["deutschland", "germany"]):
            for opt in candidate_opts:
                txt = (opt.get("text", "") if isinstance(opt, dict) else str(opt)).lower()
                val = (opt.get("value", "") if isinstance(opt, dict) else str(opt)).lower()
                if (
                    re.search(r"\b(deutschland|germany)\b", txt)
                    or re.search(r"\b(deutschland|germany)\b", val)
                    or val in ("de", "deu")
                    or txt in ("de", "deu")
                ):
                    return opt.get("value") if isinstance(opt, dict) and opt.get("value") is not None else (opt.get("text") if isinstance(opt, dict) else opt)

        return None

    def _reason_with_gemini(
        self,
        unmapped_fields: List[Dict[str, Any]],
        page_url: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Calls Google Gemini with structured CoT prompt to deduce unmapped questions."""
        # Compile candidate context for prompt (PII minimization: do not send password or irrelevant secrets)
        pers = self.profile.personal.model_dump()
        tech = self.profile.technical_skills.model_dump()
        prefs = self.profile.preferences.model_dump()
        languages = self.profile.languages
        common = self.profile.common_answers

        simplified_fields = []
        for f in unmapped_fields:
            if str(f.get("type", "")).lower() == "password":
                continue
            fid = f.get("fieldId") or f.get("id") or f.get("name")
            simplified_fields.append({
                "field_id": fid,
                "label": f.get("label", ""),
                "type": f.get("type", "text"),
                "placeholder": f.get("placeholder", ""),
                "section": f.get("sectionHeader", ""),
                "options": f.get("options", []),
            })

        prompt = f"""You are JobAgent's intelligent form-filling reasoning engine.
Analyze the following job application form fields (in German or English) and deduce the most appropriate, truthful answer for each field based on the candidate's profile and established answers.

Candidate Profile:
- Personal: {json.dumps(pers, ensure_ascii=False)}
- Languages: {json.dumps(languages, ensure_ascii=False)}
- Technical Skills: {json.dumps(tech, ensure_ascii=False)}
- Preferences: {json.dumps(prefs, ensure_ascii=False)}
- Established Answers: {json.dumps(common, ensure_ascii=False)}

Form Fields to Answer:
{json.dumps(simplified_fields, indent=2, ensure_ascii=False)}

Guidelines:
1. For language proficiency questions, match strictly against the candidate's configured "Languages" dictionary provided above. Select the option or level corresponding to the candidate's actual configured level for that language. Never invent language levels.
2. For job location questions, use the candidate's preferred work location from Preferences (Preferences.locations), or leave null if not configured. Never use their home street address.
3. For select/radio fields with options, select the exact option value or text that best matches the candidate's profile.
4. For questions regarding experience years, match against the candidate's skills.
5. For German questions, respond accurately in German or select the matching German option.
6. Work authorization, legal status, and visa requirements must be derived strictly from the candidate's profile and established answers.
7. For open essay or motivation questions (e.g. "Warum möchten Sie bei uns arbeiten?", "Why are you interested in this role?", "Motivationsschreiben"), craft a concise, professional 1-2 paragraph response tailored to the candidate's core achievements and the target role.
8. For headline or professional title questions, use the candidate's professional headline from Personal.headline.
9. For summary or bio questions, provide the candidate's professional summary in the matching language (German or English).
10. If a field cannot be answered truthfully from the profile context, leave "value" as null.

Output strictly valid JSON conforming to this schema:
{{
  "field_mappings": {{
    "<field_id>": {{
      "value": "<answer or selected option string>",
      "confidence": <float between 0.0 and 1.0>,
      "reasoning": "<brief explanation>"
    }}
  }}
}}
"""
        res_text = call_gemini_semantic_analysis(
            prompt=prompt,
            model_id=self.config.agent.model,
            temperature=self.config.agent.temperature,
        )

        if not res_text:
            return {}

        try:
            cleaned = res_text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\n", "", cleaned)
                cleaned = re.sub(r"\n```$", "", cleaned)
            parsed = json.loads(cleaned)
            return parsed.get("field_mappings", {})
        except Exception as e:
            log.warning("Failed to parse Gemini form reasoning response: %s", e, exc_info=True)
            return {}

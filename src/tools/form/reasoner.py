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

        # 1. First Name
        if any(term in combined for term in ["first name", "firstname", "vorname", "given name"]):
            first_name = pers.fullName.split()[0] if pers.fullName else ""
            return {"value": first_name, "confidence": 1.0, "reasoning": "Core profile first name"}

        # 2. Last Name
        if any(term in combined for term in ["last name", "lastname", "nachname", "familienname", "surname"]):
            parts = pers.fullName.split() if pers.fullName else []
            last_name = " ".join(parts[1:]) if len(parts) > 1 else (parts[0] if parts else "")
            return {"value": last_name, "confidence": 1.0, "reasoning": "Core profile last name"}

        # 3. Full Name
        if any(term in combined for term in ["full name", "fullname", "name", "ihr name"]) and not any(
            skip in combined for skip in ["company", "file", "user", "first", "last", "vorname", "nachname"]
        ):
            return {"value": pers.fullName, "confidence": 1.0, "reasoning": "Core profile full name"}

        # 4. Email
        if any(term in combined for term in ["email", "e-mail", "mail address", "e-mail-adresse"]) or tag_type == "email":
            return {"value": pers.email, "confidence": 1.0, "reasoning": "Core profile email"}

        # 5. Phone
        if any(term in combined for term in ["phone", "telefon", "mobile", "handy", "rufnummer", "contact number"]) or tag_type == "tel":
            return {"value": pers.phone, "confidence": 1.0, "reasoning": "Core profile phone"}

        # 6. City / Address
        if any(term in combined for term in ["city", "ort", "stadt", "wohnort", "location", "standort"]):
            city = pers.city or self._extract_city_from_address(pers.address)
            return {"value": city, "confidence": 1.0, "reasoning": "Core profile city"}

        if any(term in combined for term in ["address", "anschrift", "adresse", "street", "strasse"]):
            return {"value": pers.address, "confidence": 1.0, "reasoning": "Core profile address"}

        # 7. LinkedIn
        if "linkedin" in combined and pers.linkedinUrl:
            return {"value": pers.linkedinUrl, "confidence": 1.0, "reasoning": "Core profile LinkedIn URL"}

        # 8. GitHub / Portfolio
        if any(term in combined for term in ["github", "portfolio", "git url"]) and pers.githubUrl:
            return {"value": pers.githubUrl, "confidence": 1.0, "reasoning": "Core profile GitHub URL"}

        # 9. Salary Expectation
        if any(term in combined for term in ["salary", "gehalt", "gehaltserwartung", "compensation", "vergütung"]):
            return {"value": pers.salaryExpectation, "confidence": 0.95, "reasoning": "Core profile salary expectation"}

        # 10. Notice Period / Availability
        if any(term in combined for term in ["notice period", "kündigungsfrist", "availability", "verfügbarkeit", "eintrittstermin"]):
            return {"value": pers.noticePeriod, "confidence": 0.95, "reasoning": "Core profile notice period"}

        # 11. Work Authorization / Citizenship
        if any(term in combined for term in ["citizenship", "staatsangehörigkeit", "work authorization", "arbeitserlaubnis", "visa"]):
            return {"value": pers.citizenship, "confidence": 0.95, "reasoning": "Core profile citizenship & authorization"}

        # 12. Preferred Work Model
        if any(term in combined for term in ["work model", "arbeitsmodell", "remote", "hybrid"]):
            return {"value": prefs.workModel, "confidence": 0.90, "reasoning": "Core profile work model preference"}

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
                if val:
                    approved_mappings[fid] = val
                    reasonings[fid] = result.get("reasoning", "Deduced via Gemini 3.8 Flash")

                    # Provenance Tracking: Store suggestions with verified=0 (C3: No self-certification)
                    confidence = float(result.get("confidence", 0.0))
                    if confidence >= 0.85:
                        orig_field = next((x for x in unmapped_fields if (x.get("fieldId") or x.get("id")) == fid), None)
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

        # 1. Direct or substring match
        for opt in options:
            if isinstance(opt, dict):
                val = str(opt.get("value", "")).lower().strip()
                txt = str(opt.get("text", "")).lower().strip()
                if ans_clean == val or ans_clean == txt:
                    return opt.get("value") or opt.get("text")
                if ans_clean and (ans_clean in val or ans_clean in txt):
                    return opt.get("value") or opt.get("text")
                if val and val in ans_clean:
                    return opt.get("value") or opt.get("text")
                if txt and txt in ans_clean:
                    return opt.get("value") or opt.get("text")
            elif isinstance(opt, str):
                if ans_clean == opt.lower().strip() or ans_clean in opt.lower() or opt.lower() in ans_clean:
                    return opt

        # 2. Semantic matching for yes/no / authorization
        is_yes = any(y in ans_clean for y in ["yes", "ja", "eu", "citizen", "unrestricted", "uneingeschränkt", "full"])
        is_no = any(n in ans_clean for n in ["no", "nein", "keine", "erforderlich", "sponsorship required"])
        if is_yes and not is_no:
            for opt in options:
                txt = (opt.get("text", "") if isinstance(opt, dict) else str(opt)).lower()
                val = (opt.get("value", "") if isinstance(opt, dict) else str(opt)).lower()
                if any(y in txt or y in val for y in ["ja", "yes", "uneingeschränkt", "vorhanden", "authorized"]):
                    return opt.get("value") if isinstance(opt, dict) else opt

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
- Technical Skills: {json.dumps(tech, ensure_ascii=False)}
- Preferences: {json.dumps(prefs, ensure_ascii=False)}
- Established Answers: {json.dumps(common, ensure_ascii=False)}

Form Fields to Answer:
{json.dumps(simplified_fields, indent=2, ensure_ascii=False)}

Guidelines:
1. For select/radio fields with options, select the exact option value or text that best matches the candidate's profile.
2. For questions regarding experience years, match against the candidate's skills.
3. For German questions, respond accurately in German or select the matching German option.
4. Work authorization, legal status, and visa requirements must be derived strictly from the candidate's established answers or left as null if not specified.
5. If a field cannot be answered truthfully from the profile context, leave "value" as null.

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

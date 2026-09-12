"""Intelligent job role and title extraction engine.

Extracts job titles and roles from email subjects and snippets.
Relying on multimodal/semantic LLM reasoning as the primary engine,
with externalized heuristic pattern matching as a fast offline fallback.
Includes an in-memory normalization cache to avoid repeated LLM calls during inbox backfills.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

RULES_FILE = Path(__file__).resolve().parents[2] / "resources" / "role_extraction_rules.json"
if not RULES_FILE.exists():
    RULES_FILE = Path("resources") / "role_extraction_rules.json"


def _load_extraction_rules() -> Dict[str, Any]:
    """Loads externalized role extraction markers and patterns."""
    if RULES_FILE.exists():
        try:
            return json.loads(RULES_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Could not read %s, using defaults: %s", RULES_FILE, e)
    return {
        "non_role_subject_markers": [
            "webinar", "workshop", "coaching", "jobalert", "newsletter", "exklusiv"
        ],
        "fallback_role_patterns": [
            r'(?:als|für die Position|Position:|für die Stelle:?)\s*["“\']?([^"”\'\n\r/]+)',
            r'(?:role:|position:|job title:|application for|applied for:?|as a[n]?)\s*["“\']?([^"”\'\n\r/]+)',
        ],
    }


class RoleExtractor:
    """Extracts job titles/roles from subjects or snippets using LLM + fast fallback."""

    def __init__(self, rules: Optional[Dict[str, Any]] = None):
        self.rules = rules or _load_extraction_rules()
        self.non_role_markers: List[str] = self.rules.get("non_role_subject_markers", [])
        self.fallback_patterns: List[str] = self.rules.get("fallback_role_patterns", [])
        self._role_cache: Dict[str, Optional[str]] = {}

    def extract_role_with_llm(self, subject: str, snippet: str = "") -> Optional[str]:
        """Uses Gemini Flash semantic reasoning to deduce the job role from subject/snippet."""
        if not os.getenv("GEMINI_API_KEY"):
            return None

        try:
            from src.core.llm_provider import call_gemini_semantic_analysis
        except ImportError:
            return None

        prompt = (
            "You are an expert HR assistant. Given the following email subject and snippet, "
            "extract the exact job role or job title (e.g. 'Senior Cloud Architect', 'Backend Developer', 'Data Engineer').\n"
            "If this email is promotional, a marketing pitch, coaching, or does not mention a real job opening, return null.\n\n"
            f"Subject: {subject}\n"
            f"Snippet: {snippet[:500]}\n\n"
            "Return ONLY a JSON object: {\"role\": \"Job Title or null\"}"
        )

        try:
            res = call_gemini_semantic_analysis(prompt)
            if not res:
                return None
            cleaned = res.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0].strip()
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0].strip()
            data = json.loads(cleaned)
            role = data.get("role")
            if role and isinstance(role, str) and len(role.strip()) >= 3 and role.lower() != "null":
                return role.strip()
        except Exception as e:
            log.debug("LLM role extraction failed: %s", e)
        return None

    def extract_role(self, subject: str, snippet: str = "", use_llm: bool = True) -> Optional[str]:
        """Extracts job role from context. Attempts LLM first, then falls back to rules.
        Uses normalized subject caching to avoid redundant LLM calls on large backfills.
        """
        if not subject:
            return None

        cache_key = re.sub(r"\s+", " ", subject.strip().lower())
        if cache_key in self._role_cache:
            return self._role_cache[cache_key]

        role: Optional[str] = None

        # 1. Primary: Intelligent LLM semantic extraction
        if use_llm and os.getenv("GEMINI_API_KEY"):
            role = self.extract_role_with_llm(subject, snippet)

        # 2. Fallback: Fast heuristic extraction
        if not role:
            lower_subj = subject.lower()
            if not any(marker in lower_subj for marker in self.non_role_markers):
                for pattern in self.fallback_patterns:
                    m = re.search(pattern, subject, flags=re.IGNORECASE)
                    if m:
                        extracted = m.group(1).strip().strip("\"'“”.,:;").strip()
                        if len(extracted) >= 3:
                            role = extracted
                            break

        self._role_cache[cache_key] = role
        return role


# Global singleton instance
_default_extractor = RoleExtractor()


def extract_role_from_context(subject: str, snippet: str = "", use_llm: bool = True) -> Optional[str]:
    """Convenience helper for extracting a job role from subject or text snippet."""
    return _default_extractor.extract_role(subject, snippet, use_llm=use_llm)

"""Extracts job location and work mode directly from text without hardcoded city dictionaries.

Parses structural location fields (Location:, Standort:, Ort:) and work modes (Remote, Hybrid)
directly from job descriptions, email correspondence, and application metadata.
"""

from __future__ import annotations

import re
from typing import Optional


# Work mode patterns
REMOTE_PATTERN = re.compile(
    r"\b(100\s*%\s*remote|fully\s*remote|remote\s*first|vollst[äa]ndig\s*im\s*homeoffice|homeoffice|remote)\b",
    re.IGNORECASE,
)

HYBRID_PATTERN = re.compile(
    r"\b(hybrid|teilweise\s*homeoffice|mobiles\s*arbeiten)\b",
    re.IGNORECASE,
)

# Structural location field patterns commonly found in job descriptions and application summaries
LOCATION_FIELD_PATTERN = re.compile(
    r"\b(?:location|standort|ort|arbeitsort|city)\s*[:\-]\s*([A-Za-zÄÖÜäöüß0-9\s\-\/\(\),]{2,40})(?:\r|\n|;|\.|$)",
    re.IGNORECASE,
)

# Postal code + city pattern (e.g., '10587 Berlin', 'D-60311 Frankfurt am Main')
POSTAL_CITY_PATTERN = re.compile(
    r"\b(?:D-)?(\d{5})\s+([A-ZÄÖÜ][a-zäöüß]+(?:(?:[\s\-]+(?:am|an\s+der|im|in\s+der)[\s\-]+|[\s\-])[A-ZÄÖÜ][a-zäöüß]+)*)\b"
)


def extract_location(*text_sources: Optional[str]) -> Optional[str]:
    """Extracts location directly from text sources without relying on hardcoded city lists.
    
    Returns strings like:
      - 'Frankfurt am Main' (extracted from 'Location: Frankfurt am Main' or '60311 Frankfurt am Main')
      - 'Berlin (Remote)'
      - 'Remote'
      - 'Hybrid'
    or None if no confident location is specified.
    """
    combined = " ".join(t for t in text_sources if t).strip()
    if not combined:
        return None

    is_remote = bool(REMOTE_PATTERN.search(combined))
    is_hybrid = bool(HYBRID_PATTERN.search(combined))

    # 1. Look for structural location field in the text
    field_match = LOCATION_FIELD_PATTERN.search(combined)
    found_location: Optional[str] = None

    if field_match:
        candidate = field_match.group(1).strip(" -,\t")
        # Ensure candidate is not a generic placeholder
        if len(candidate) >= 2 and candidate.lower() not in ("remote", "hybrid", "homeoffice", "n/a", "none"):
            found_location = candidate

    # 2. Fall back to postal code / address structure matching
    if not found_location:
        postal_match = POSTAL_CITY_PATTERN.search(combined)
        if postal_match:
            city_candidate = postal_match.group(2).strip(" -,\t|Ι")
            if len(city_candidate) >= 2 and city_candidate.lower() not in ("remote", "hybrid", "homeoffice", "germany", "deutschland"):
                found_location = city_candidate

    # 2. Combine extracted text with work mode
    if found_location:
        has_remote = bool(REMOTE_PATTERN.search(found_location))
        has_hybrid = bool(HYBRID_PATTERN.search(found_location))
        if is_remote and not has_remote:
            return f"{found_location} (Remote)"
        if is_hybrid and not has_hybrid:
            return f"{found_location} (Hybrid)"
        return found_location

    if is_remote:
        return "Remote"
    if is_hybrid:
        return "Hybrid"

    return None

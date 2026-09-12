"""Entity normalization and noise filtering for companies and job roles.

Eliminates duplicates caused by:
- Legal suffixes (GmbH, AG, SE, Inc, Ltd, Holding, etc.)
- Functional department suffixes (HR, Recruiting, Talent Acquisition, Team, etc.)
- Platform/aggregator notices (LinkedIn, BambooHR, Join.com, etc.)
- Placeholder roles (Candidate, Bewerber, Apply With LinkedIn)
- German grammar declensions and leading artefacts
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
from typing import Dict, Optional, Set

log = logging.getLogger(__name__)

# Non-company aggregators, relay domains, and noise strings
NOISE_COMPANY_PATTERNS: Set[str] = {
    "linkedin",
    "h linkedin",
    "apply with linkedin",
    "bewerben mit linkedin",
    "stepstone",
    "indeed",
    "join.com",
    "bamboohr",
    "notifications@app.bamboohr.com",
    "personio",
    "greenhouse",
    "workday",
    "lever",
    "smartrecruiters",
    "softgarden",
    "dvinci",
    "recruitee",
    "ashby",
    "recruiting",
    "talent acquisition",
    "karriere",
    "karriere-team",
    "recruiting-team",
    "hiring-team",
    "hr-team",
    "bewerbung",
    "bewerbungen",
    "careers",
    "noreply",
    "no-reply",
    "donotreply",
    "candidate",
    "bewerber",
    "unknown",
    "unbekannt",
    "uns eingegangen",
    "ist eingegangen",
    "bewerbung eingegangen",
}

# Legal company forms and geographic entity suffixes to strip
LEGAL_FORM_REGEX = re.compile(
    r"\s+(?:GmbH\s*&\s*Co\.?\s*KG[aA]?|GmbH\s*&\s*Co\.?|GmbH|AG|SE|Holding|KGaA|KG|GbR|OHG|e\.?V\.?|Ltd\.?|Inc\.?|Corp(?:oration)?\.?|PLC|LLC|LLP|Co\.?|Germany|Deutschland|DACH|Europe)\.?$",
    re.IGNORECASE,
)

# Functional department suffixes to strip (HR, Recruiting, Team, etc.)
FUNCTIONAL_SUFFIX_REGEX = re.compile(
    r"\s+(?:HR(?:\s*-\s*Team|\s+Team)?|Recruiting(?:\s*-\s*Team|\s+Team)?|Talent\s+Acquisition|Karriere(?:\s*-\s*Team|\s+Team)?|Bewerbermanagement|Datenschutz|Team|Hiring\s+Team)\.?$",
    re.IGNORECASE,
)

# Placeholder roles that should be overridden by concrete job titles
PLACEHOLDER_ROLES: Set[str] = {
    "candidate",
    "bewerber",
    "bewerberin",
    "bewerbung",
    "apply with linkedin",
    "consultant",  # when generic placeholder
    "general application",
    "spontanbewerbung",
    "initiativbewerbung",
    "unknown",
    "unbekannt",
    "unbekannt (bitte prüfen)",
}

GENDER_TAGS_REGEX = re.compile(
    r"\s*(?:\([mfdwa/,\s\+\-]+\)|\[[mfdwa/,\s\+\-]+\]|\*[/\*\s\w]*|\(all genders\)|(?:all genders, full-/part-time)|\(all genders / Part-fulltime\))\s*",
    re.IGNORECASE,
)

# Optional external company aliases loader (strictly git-ignored for private mapping)
_CACHED_ALIASES: Optional[Dict[str, str]] = None


def _load_company_aliases() -> Dict[str, str]:
    """Loads company aliases from local gitignored file or config."""
    global _CACHED_ALIASES
    if _CACHED_ALIASES is not None:
        return _CACHED_ALIASES

    aliases: Dict[str, str] = {}
    # Priority 1: company_aliases.local.json
    local_path = Path("company_aliases.local.json")
    if local_path.exists():
        try:
            aliases.update(json.loads(local_path.read_text(encoding="utf-8")))
        except Exception as err:
            log.debug("Could not load company_aliases.local.json: %s", err)

    # Priority 2: resources/company_aliases.json
    shared_path = Path(__file__).resolve().parents[2] / "resources" / "company_aliases.json"
    if not shared_path.exists():
        shared_path = Path("resources") / "company_aliases.json"
    if shared_path.exists():
        try:
            aliases.update(json.loads(shared_path.read_text(encoding="utf-8")))
        except Exception as err:
            log.debug("Could not load shared company_aliases.json: %s", err)

    _CACHED_ALIASES = {k.strip().lower(): v.strip() for k, v in aliases.items()}
    return _CACHED_ALIASES


def is_noise_company(company: Optional[str]) -> bool:
    """Returns True if company is an email aggregator, ATS relay, or non-company noise."""
    if not company:
        return True
    clean = company.strip().lower()

    if len(clean) < 2:
        return True

    clean_words = " ".join(re.sub(r"[^\w\s@.]", " ", clean).split())
    if clean in NOISE_COMPANY_PATTERNS or clean_words in NOISE_COMPANY_PATTERNS:
        return True

    for noise in NOISE_COMPANY_PATTERNS:
        if clean == noise or clean_words == noise or clean.startswith(noise + " ") or clean.endswith(" " + noise):
            return True

    if "@" in clean:
        return True

    if clean.endswith(".com") or clean.endswith(".de"):
        if any(ats in clean for ats in ["bamboohr", "join", "personio", "greenhouse", "workday", "lever", "recruitee"]):
            return True

    if clean.startswith("h linkedin") or clean == "linkedin" or "linkedin" in clean.split():
        return True

    return False


def normalize_company_name(name: Optional[str]) -> str:
    """Normalizes company name into a clean canonical token for clustering and deduplication.
    
    Strips:
    - Legal form suffixes (GmbH, AG, Holding, Inc, etc.)
    - Department & functional suffixes (HR, Recruiting, Talent Acquisition, etc.)
    - Webmailer and relay noise
    - German grammatical declensions
    """
    if not name:
        return ""

    s = name.strip()
    s = re.sub(r"^[^\w]+", "", s)
    s = re.sub(r"^webmailer\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"[-_](?:recruit|no-?reply).*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+(?:ist\s+bei\s+uns\s+eingegangen|ist\s+eingegangen|eingegangen|als|für|fuer)$", "", s, flags=re.IGNORECASE)

    # Iteratively strip legal form and functional department suffixes
    for _ in range(4):
        prev = s
        s = LEGAL_FORM_REGEX.sub("", s).strip()
        s = FUNCTIONAL_SUFFIX_REGEX.sub("", s).strip()
        if s == prev:
            break

    # Clean German grammatical declensions
    if s.lower().startswith("deutschen "):
        s = "Deutsche " + s[10:]
    elif s.lower().startswith("dfv "):
        s = s[4:]

    # Check externalized aliases
    aliases = _load_company_aliases()
    low = s.lower()
    if low in aliases:
        s = aliases[low]

    s = s.strip(" .,;:-/|")

    # Capitalize if lowercase
    if s.islower() and len(s) > 1 and not (s in aliases and aliases[s] == s):
        s = s.capitalize()

    return s


def normalize_role_title(role: Optional[str]) -> Optional[str]:
    """Cleans job titles, strips gender tags and leading noise, and filters placeholders."""
    if not role:
        return None

    r = role.strip()
    r_lower = r.lower()
    if r_lower in PLACEHOLDER_ROLES or r_lower.startswith("unbekannt"):
        return None

    r = GENDER_TAGS_REGEX.sub("", r).strip()
    r = re.sub(r"^(?:of\s+|r\s+Stelle:\s*|Stelle:\s*|für\s+|fuer\s+|Position:\s*|als\s+)", "", r, flags=re.IGNORECASE).strip()
    r = re.sub(r"\s*[-|/]\s*(?:Germany|Deutschland|Remote|bis\s+\d+.*)$", "", r, flags=re.IGNORECASE).strip()
    r = re.sub(r"\s+", " ", r).strip(" .,;:-")

    if len(r) < 3 or r.lower() in PLACEHOLDER_ROLES or r.lower().startswith("unbekannt"):
        return None

    return r

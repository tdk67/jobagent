"""Entity normalization and noise filtering for companies and job roles.

Eliminates duplicates caused by:
- Legal suffixes (GmbH, AG, SE, Inc, Ltd, Holding, etc.)
- Platform/aggregator notices (LinkedIn, BambooHR, Join.com, etc.)
- Placeholder roles (Candidate, Bewerber, Apply With LinkedIn)
- German grammar declensions and leading artefacts
"""

from __future__ import annotations

import re
from typing import Optional, Set

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
}

GENDER_TAGS_REGEX = re.compile(
    r"\s*(?:\([mfdwa/,\s\+\-]+\)|\[[mfdwa/,\s\+\-]+\]|\*[/\*\s\w]*|\(all genders\)|(?:all genders, full-/part-time)|\(all genders / Part-fulltime\))\s*",
    re.IGNORECASE,
)


def is_noise_company(company: Optional[str]) -> bool:
    """Returns True if company is an email aggregator, ATS relay, or non-company noise."""
    if not company:
        return True
    clean = company.strip().lower()

    if len(clean) < 2:
        return True

    # Check normalized with spaces instead of hyphens
    clean_words = " ".join(re.sub(r"[^\w\s@.]", " ", clean).split())
    if clean in NOISE_COMPANY_PATTERNS or clean_words in NOISE_COMPANY_PATTERNS:
        return True

    # Check if any noise pattern matches
    for noise in NOISE_COMPANY_PATTERNS:
        if clean == noise or clean_words == noise or clean.startswith(noise + " ") or clean.endswith(" " + noise):
            return True

    # Check for email address (any string with @ is an email address, not a company name)
    if "@" in clean:
        return True

    # Check for ATS domain noise
    if clean.endswith(".com") or clean.endswith(".de"):
        if any(ats in clean for ats in ["bamboohr", "join", "personio", "greenhouse", "workday", "lever", "recruitee"]):
            return True

    # Check if starts with "h linkedin" or "linkedin"
    if clean.startswith("h linkedin") or clean == "linkedin" or "linkedin" in clean.split():
        return True

    return False


def normalize_company_name(name: Optional[str]) -> str:
    """Normalizes company name into a clean canonical token for clustering and deduplication.
    
    Examples:
    - 'Ratbacher GmbH' -> 'Ratbacher'
    - 'Ratbacher' -> 'Ratbacher'
    - 'trendtours Holding GmbH' -> 'Trendtours'
    - 'DFV Deutsche Familienversicherung AG' -> 'Deutsche Familienversicherung'
    - 'Deutschen Familienversicherung' -> 'Deutsche Familienversicherung'
    - 'Appian Corporation' -> 'Appian'
    - 'ITSG GmbH' -> 'ITSG'
    - 'HMS-Recruit-no-reply' -> 'HMS Networks'
    - 'DekaBank Deutsche Girozentrale ist eingegangen' -> 'DekaBank Deutsche Girozentrale'
    """
    if not name:
        return ""

    s = name.strip()
    # Remove leading non-word characters or artifacts like 'h ' from 'h LinkedIn'
    s = re.sub(r"^[^\w]+", "", s)

    # Strip webmailer prefix (e.g. 'Webmailer Amadeus Fire' -> 'Amadeus Fire')
    s = re.sub(r"^webmailer\s+", "", s, flags=re.IGNORECASE)

    # Strip email/relay suffix artifacts like -Recruit-no-reply
    s = re.sub(r"[-_](?:recruit|no-?reply).*$", "", s, flags=re.IGNORECASE)

    # Strip trailing email subject fragments like 'ist eingegangen', 'eingegangen', 'als', 'für'
    s = re.sub(r"\s+(?:ist\s+bei\s+uns\s+eingegangen|ist\s+eingegangen|eingegangen|als|für|fuer)$", "", s, flags=re.IGNORECASE)

    # Strip legal form suffixes repeatedly (e.g. 'Holding GmbH')
    for _ in range(3):
        new_s = LEGAL_FORM_REGEX.sub("", s).strip()
        if new_s == s:
            break
        s = new_s

    # Clean German grammatical declensions: 'Deutschen Familienversicherung' -> 'Deutsche Familienversicherung'
    if s.lower().startswith("deutschen "):
        s = "Deutsche " + s[10:]
    elif s.lower().startswith("dfv "):
        s = s[4:]

    # Normalize known aliases
    low = s.lower()
    if low in ("hms", "hms-recruit", "hms networks"):
        s = "HMS Networks"
    elif low in ("dekabank", "dekabank deutsche girozentrale", "deka"):
        s = "DekaBank"
    elif low in ("dwpbank", "deutsche wertpapierservice bank"):
        s = "dwpbank"

    # Remove trailing punctuation or whitespace
    s = s.strip(" .,;:-/|")

    # Capitalize appropriately if all lowercase (except recognized brands like dwpbank)
    if s.islower() and len(s) > 1 and s != "dwpbank":
        s = s.capitalize()

    return s


def normalize_role_title(role: Optional[str]) -> Optional[str]:
    """Cleans job titles, strips gender tags and leading noise, and filters placeholders.
    
    Examples:
    - 'of Senior Backend Engineer - Germany' -> 'Senior Backend Engineer'
    - 'r Stelle: Senior Java Software Entwickler' -> 'Senior Java Software Entwickler'
    - 'Software Quality Lead - QA & Test Management (m/w/d)' -> 'Software Quality Lead - QA & Test Management'
    - 'Candidate' -> None (placeholder)
    """
    if not role:
        return None

    r = role.strip()
    # Check if placeholder
    if r.lower().strip() in PLACEHOLDER_ROLES:
        return None

    # Strip gender tags
    r = GENDER_TAGS_REGEX.sub("", r).strip()

    # Strip leading grammar/preposition fragments: 'of ', 'r Stelle: ', 'fuer ', 'für '
    r = re.sub(r"^(?:of\s+|r\s+Stelle:\s*|Stelle:\s*|für\s+|fuer\s+|Position:\s*|als\s+)", "", r, flags=re.IGNORECASE).strip()

    # Strip trailing location qualifiers like '- Germany', '| Raum Hanau', etc.
    r = re.sub(r"\s*[-|/]\s*(?:Germany|Deutschland|Remote|bis\s+\d+.*)$", "", r, flags=re.IGNORECASE).strip()

    # Clean double whitespace
    r = re.sub(r"\s+", " ", r).strip(" .,;:-")

    if len(r) < 3 or r.lower() in PLACEHOLDER_ROLES:
        return None

    return r

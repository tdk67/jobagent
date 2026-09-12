"""Extracts job application channel (ATS platform, job board, or company portal).

Dynamically derives application channels from sender email addresses and job URLs
by extracting the platform domain, eliminating brittle hardcoded rule lists.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# Common generic consumer email providers where domain is not the employer/ATS
CONSUMER_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "yahoo.com",
    "yahoo.de",
    "gmx.de",
    "gmx.net",
    "web.de",
    "t-online.de",
    "icloud.com",
}

# Optional external alias dictionary for cosmetic formatting (e.g. BambooHR vs Bamboohr)
_CHANNEL_ALIASES: Optional[Dict[str, str]] = None


def _get_channel_aliases() -> Dict[str, str]:
    """Loads optional cosmetic channel name mappings from external config."""
    global _CHANNEL_ALIASES
    if _CHANNEL_ALIASES is None:
        _CHANNEL_ALIASES = {}
        alias_file = Path("resources/channel_aliases.json")
        if alias_file.exists():
            try:
                _CHANNEL_ALIASES = json.loads(alias_file.read_text(encoding="utf-8"))
            except Exception as e:
                log.debug("Could not read resources/channel_aliases.json: %s", e)
    return _CHANNEL_ALIASES


def extract_channel_from_domain(domain: str) -> Optional[str]:
    """Dynamically extracts the platform name from any internet domain without hardcoded rules.
    
    Examples:
      - 'no-reply@ashbyhq.com' -> 'Ashby'
      - 'jobs.lever.co' -> 'Lever'
      - 'boards.greenhouse.io' -> 'Greenhouse'
      - 'recruiting.personio.de' -> 'Personio'
      - 'company.bamboohr.com' -> 'BambooHR'
      - 'future-new-board.xyz' -> 'Future-New-Board'
    """
    if not domain:
        return None

    clean = domain.strip().lower()
    if clean in CONSUMER_DOMAINS:
        return None

    # Remove port if present
    if ":" in clean:
        clean = clean.split(":")[0]

    # Split domain into components
    parts = clean.split(".")
    if len(parts) < 2:
        return None

    # Remove known generic subdomains
    while len(parts) > 2 and parts[0] in {
        "mail", "email", "recruiting", "jobs", "careers", "talent",
        "boards", "app", "apply", "notifications", "notify", "bounce", "www",
    }:
        parts.pop(0)

    # Secondary level domain is typically parts[-2]
    # Handle two-part TLDs like .co.uk or .com.de
    if len(parts) >= 3 and parts[-1] in {"uk", "de", "at", "ch", "au", "br"} and parts[-2] in {"co", "com", "org", "net"}:
        slug = parts[-3]
    else:
        slug = parts[-2]

    # Check optional cosmetic alias mapping first
    aliases = _get_channel_aliases()
    if slug in aliases:
        return aliases[slug]

    # Strip trailing "hq" (e.g. ashbyhq -> Ashby, pinpointhq -> Pinpoint)
    base_name = slug
    if base_name.endswith("hq") and len(base_name) > 4:
        base_name = base_name[:-2]

    # Capitalize hyphenated or underscored tokens dynamically
    formatted = "-".join(segment.capitalize() for segment in base_name.split("-"))
    return formatted if formatted else None


def extract_channel(
    sender_email: Optional[str] = None,
    job_url: Optional[str] = None,
    sender_name: Optional[str] = None,
    existing_source: Optional[str] = None,
) -> str:
    """Extracts a specific application channel from sender email, URL, or sender name dynamically.
    
    Works for any current or future job board / ATS without code modifications.
    """
    # 1. Try extracting domain from sender_email
    if sender_email and "@" in sender_email:
        email_domain = sender_email.split("@")[-1].strip()
        channel = extract_channel_from_domain(email_domain)
        if channel:
            return channel

    # 2. Try extracting domain from job_url
    if job_url and "://" in job_url:
        try:
            parsed = urlparse(job_url)
            channel = extract_channel_from_domain(parsed.netloc)
            if channel:
                return channel
        except Exception:
            pass

    # 3. Preserve existing valid source if not a generic placeholder
    if existing_source and existing_source not in ("Direct / ATS", "Direct", "Email Ingestion", "", "—"):
        return existing_source

    return "Direct"

"""Multilingual date parsing utilities for JobAgent.

Supports flexible human-entered and scraped dates across English, German,
and standard ISO representations without hardcoded month dictionaries.
Uses the `dateparser` and `python-dateutil` libraries.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional

import dateparser
from dateutil import parser as dateutil_parser

log = logging.getLogger(__name__)


def parse_flexible_date(date_input: Optional[Any]) -> Optional[str]:
    """Parses flexible date inputs into ISO format YYYY-MM-DD.

    Supports:
    - ISO strings: '2026-07-01', '2026-07-01T12:00:00Z'
    - European numeric: '01.07.2026', '1.7.2026', '01.07.'
    - English text: '1-Jul', '1-Jul-2026', 'July 1, 2026', '1 July 2026'
    - German text: '1. März 2026', '15. Oktober 2026', '1. Mai'
    - datetime / date objects

    Returns:
        ISO date string 'YYYY-MM-DD', or None if input is empty or unparseable.
    """
    if not date_input:
        return None

    if isinstance(date_input, (datetime, date)):
        return date_input.strftime("%Y-%m-%d")

    s = str(date_input).strip()
    if not s:
        return None

    # Fast-path for standard ISO 10-char date (YYYY-MM-DD)
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Use dateparser with Day-First (European) bias and current year default
    current_year = datetime.now().year
    try:
        parsed_dt = dateparser.parse(
            s,
            languages=["de", "en"],
            settings={
                "DATE_ORDER": "DMY",
                "PREFER_DAY_OF_MONTH": "first",
            },
        )
        if parsed_dt:
            # If the input was e.g. "1-Jul" or "01.07." without explicit year,
            # dateparser defaults to current year. Ensure sensible bounds.
            if parsed_dt.year < 100:
                parsed_dt = parsed_dt.replace(year=parsed_dt.year + 2000)
            return parsed_dt.strftime("%Y-%m-%d")
    except Exception as e:
        log.debug("dateparser failed on %r: %s", s, e)

    # Fallback to dateutil parser
    try:
        parsed_dt = dateutil_parser.parse(s, dayfirst=True, default=datetime(current_year, 1, 1))
        return parsed_dt.strftime("%Y-%m-%d")
    except Exception:
        return None

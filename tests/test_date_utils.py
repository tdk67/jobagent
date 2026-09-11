"""Tests for multilingual date parsing utilities."""

from datetime import date, datetime
from src.utils.date_utils import parse_flexible_date


def test_parse_flexible_date_iso_and_types():
    assert parse_flexible_date(datetime(2026, 7, 1, 10, 30)) == "2026-07-01"
    assert parse_flexible_date(date(2026, 7, 1)) == "2026-07-01"
    assert parse_flexible_date("2026-07-01") == "2026-07-01"
    assert parse_flexible_date("2026-07-01T15:45:00Z") == "2026-07-01"


def test_parse_flexible_date_european_numeric():
    assert parse_flexible_date("01.07.2026") == "2026-07-01"
    assert parse_flexible_date("1.7.2026") == "2026-07-01"
    assert parse_flexible_date("15.09.2026") == "2026-09-15"


def test_parse_flexible_date_english_text():
    assert parse_flexible_date("1-Jul-2026") == "2026-07-01"
    assert parse_flexible_date("1 July 2026") == "2026-07-01"
    assert parse_flexible_date("July 1, 2026") == "2026-07-01"
    assert parse_flexible_date("September 15, 2026") == "2026-09-15"
    # Year omitted assumes current year (e.g. 2026)
    res_jul = parse_flexible_date("1-Jul")
    assert res_jul is not None
    assert res_jul.endswith("-07-01")


def test_parse_flexible_date_german_text():
    # German month names with umlauts
    assert parse_flexible_date("1. März 2026") == "2026-03-01"
    assert parse_flexible_date("15. Oktober 2026") == "2026-10-15"
    assert parse_flexible_date("10. Mai 2026") == "2026-05-10"
    assert parse_flexible_date("01. Dezember 2026") == "2026-12-01"


def test_parse_flexible_date_invalid_and_empty():
    assert parse_flexible_date(None) is None
    assert parse_flexible_date("") is None
    assert parse_flexible_date("   ") is None
    assert parse_flexible_date("not-a-date") is None
    assert parse_flexible_date("xyz123456789") is None

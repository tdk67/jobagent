"""Tests for JobAgent SQLite storage repository."""

import json

from pathlib import Path
from src.core.storage import UNKNOWN_ROLE, JobAgentStorage, parse_flexible_date


def test_storage_crud(tmp_path: Path):
    db_path = tmp_path / "test_jobagent.db"
    storage = JobAgentStorage(db_path=str(db_path))

    # 1. Upsert application
    app_id = storage.upsert_application(
        company="Acme Corp",
        role="Senior Python Engineer",
        applied_date="2026-09-01T10:00:00Z",
        status="Applied",
        source="LinkedIn",
        location="Frankfurt am Main",
    )
    assert app_id > 0

    # 2. Query application
    app = storage.get_application_by_company("Acme Corp")
    assert app is not None
    assert app["company"] == "Acme"
    assert app["role"] == "Senior Python Engineer"
    assert app["status"] == "Applied"

    # 3. Record interview
    interview_id, created = storage.record_interview(
        company="Acme Corp",
        interview_date="2026-09-15T14:00:00Z",
        role="Senior Python Engineer",
        application_id=app_id,
        interview_type="Technical Interview",
        meeting_link="https://teams.microsoft.com/l/meetup-join/123",
    )
    assert interview_id > 0
    assert created is True

    # Duplicate call must return created=False
    dup_id, dup_created = storage.record_interview(
        company="Acme Corp",
        interview_date="2026-09-15T14:00:00Z",
    )
    assert dup_id == interview_id
    assert dup_created is False

    # Verify status changed to Interview
    updated_app = storage.get_application_by_company("Acme Corp")
    assert updated_app["status"] == "Interview"

    # 4. QA Memory (C3 verification gating)
    storage.save_qa_answer("What is your expected salary?", "85,000 EUR", "compensation", verified=1)
    ans = storage.get_qa_answer("expected salary")
    assert ans == "85,000 EUR"

    # Unverified suggestion should NOT be returned when verified_only=True
    storage.save_qa_answer("Do you have driver license?", "Yes, Class B", verified=0, provenance="llm_suggested")
    assert storage.get_qa_answer("driver license", verified_only=True) is None
    assert storage.get_qa_answer("driver license", verified_only=False) == "Yes, Class B"

    # 5. Statistics
    stats = storage.get_statistics()
    assert stats["total_applications"] == 1
    assert stats["total_interviews"] == 1
    assert stats["response_rate_percent"] == 100.0

    # 6. Export summary
    summary = storage.export_summary_json()
    assert summary["total_count"] == 1
    assert len(summary["applications"]) == 1
    assert summary["applications"][0]["company"] == "Acme"
    assert summary["applications"][0]["location"] == "Frankfurt am Main"

    # 7. Test application without location defaults to neutral marker "—"
    storage.upsert_application(
        company="Remote Works",
        role="DevOps Specialist",
        applied_date="2026-09-02T12:00:00Z",
    )
    summary2 = storage.export_summary_json()
    remote_app = next(a for a in summary2["applications"] if a["company"] == "Remote Works")
    assert remote_app["location"] == "—"
    assert "Frankfurt" not in remote_app["location"]


def _write_summary_file(tmp_path: Path, company: str, subject: str) -> str:
    """Writes a minimal applications_summary.json with an unparseable job_title."""
    summary = {
        "applications": [
            {
                "company": company,
                "job_title": "",
                "emails": [{"subject": subject}],
                "application_date": "2026-08-01T10:00:00Z",
                "status": "Applied",
                "email_count": 1,
            }
        ]
    }
    summary_path = tmp_path / "applications_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    return str(summary_path)


def test_import_from_summary_unparseable_role_uses_unknown_placeholder(tmp_path: Path):
    """F5 VP1: subject with no parseable role must NOT fabricate a role."""
    db_path = tmp_path / "import_unknown.db"
    storage = JobAgentStorage(db_path=str(db_path))
    summary_path = _write_summary_file(tmp_path, "Fiktive GmbH", "Rückmeldung zu Ihrer Bewerbung")

    res = storage.import_from_summary(summary_path)
    assert res["applications_imported"] == 1

    app = storage.get_application_by_company("Fiktive GmbH")
    assert app is not None
    assert app["role"] == UNKNOWN_ROLE
    assert app["role"] != "Senior Software Engineer"


def test_import_from_summary_does_not_overwrite_real_role_with_placeholder(tmp_path: Path):
    """F5 VP1: a second import pass must not clobber a real role with the placeholder."""
    db_path = tmp_path / "import_keep.db"
    storage = JobAgentStorage(db_path=str(db_path))
    summary_path = _write_summary_file(tmp_path, "Musterfirma AG", "Keine Position erkennbar")

    storage.import_from_summary(summary_path)
    app = storage.get_application_by_company("Musterfirma AG")
    assert app is not None and app["role"] == UNKNOWN_ROLE

    # A later flow (e.g. user correction) stores the real role.
    with storage._get_connection() as conn:
        conn.execute("UPDATE applications SET role = ? WHERE id = ?", ("Backend Engineer", app["id"]))

    # Second import pass must NOT overwrite the real role with the placeholder.
    storage.import_from_summary(summary_path)
    app_after = storage.get_application_by_company("Musterfirma AG")
    assert app_after is not None
    assert app_after["role"] == "Backend Engineer"


def test_import_from_summary_interviews_use_unknown_role_placeholder(tmp_path: Path):
    """F5: interview import branch must not fabricate "Senior Software Engineer"."""
    db_path = tmp_path / "import_interviews.db"
    storage = JobAgentStorage(db_path=str(db_path))
    summary_path = _write_summary_file(tmp_path, "Interviewfirma GmbH", "Kontaktaufnahme")
    int_path = tmp_path / "interviews_consolidated.json"
    int_path.write_text(
        json.dumps([{"company": "Interviewfirma GmbH", "interview_type": "Video", "latest_date": "2026-08-10"}], ensure_ascii=False),
        encoding="utf-8",
    )

    res = storage.import_from_summary(summary_path, interviews_path=str(int_path))
    assert res["interviews_imported"] == 1

    interviews = storage.list_interviews()
    assert interviews
    assert interviews[0]["role"] == UNKNOWN_ROLE


def test_parse_flexible_date_valid_and_invalid():
    """Verify parse_flexible_date parses known patterns and returns None on unparseable garbage."""
    # Valid formats
    assert parse_flexible_date("2026-07-01") == "2026-07-01"
    assert parse_flexible_date("01.07.2026") == "2026-07-01"
    assert parse_flexible_date("1.7.2026") == "2026-07-01"
    assert parse_flexible_date("1-Jul-2026") == "2026-07-01"
    assert parse_flexible_date("1 July 2026") == "2026-07-01"

    # Empty / None
    assert parse_flexible_date(None) is None
    assert parse_flexible_date("") is None
    assert parse_flexible_date("   ") is None

    # Unparseable garbage should return None, NOT truncated garbage strings (C15 fix)
    assert parse_flexible_date("unparseable_garbage") is None
    assert parse_flexible_date("invalid-date-string") is None
    assert parse_flexible_date("abcdefghijklmnop") is None


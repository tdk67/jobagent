"""Tests for JobAgent SQLite storage repository."""

from pathlib import Path
from src.core.storage import JobAgentStorage


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
    assert app["company"] == "Acme Corp"
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
    assert summary["applications"][0]["company"] == "Acme Corp"
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

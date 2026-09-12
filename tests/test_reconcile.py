"""Unit tests for repository-based reconciliation and human approval tracking."""

from __future__ import annotations

from pathlib import Path
import pytest
from src.core.storage import JobAgentStorage
from src.tools.email.reconcile import reconcile_database


@pytest.fixture
def temp_db(tmp_path: Path) -> JobAgentStorage:
    db_file = tmp_path / "test_reconcile.db"
    return JobAgentStorage(str(db_file))


def test_reconcile_unlinked_via_storage(temp_db: JobAgentStorage):
    # 1. Create an application
    app_id = temp_db.upsert_application(
        company="Acme Corp",
        role="Backend Engineer",
        status="Applied",
        applied_date="2026-09-10",
    )
    assert app_id is not None and app_id > 0

    # 2. Record an unlinked interaction
    temp_db.record_email_interaction(
        entry_id="entry_reconcile_1",
        category="application_confirmation",
        sender_name="Acme Recruiting",
        sender_email="recruiting@acme-corp.com",
        subject="Your application at Acme Corp",
        received_time="2026-09-10T10:00:00Z",
        preview="Thank you for applying to Acme Corp",
        application_id=None,
    )

    # 3. Run reconciliation via facade
    res = reconcile_database(db_path=str(temp_db.db_path))
    assert res["emails_reconciled"] >= 1

    # Verify interaction is now linked
    emails = temp_db.get_application_emails(app_id)
    assert len(emails) >= 1
    assert emails[0]["entry_id"] == "entry_reconcile_1"


def test_pending_approvals_lifecycle(temp_db: JobAgentStorage):
    approval_id = temp_db.create_pending_approval(
        question="Confirm interview on Tuesday at 14:00?",
        context="Acme Corp technical interview invitation",
        urgency="high",
    )
    assert approval_id > 0

    pending = temp_db.list_pending_approvals(status="pending")
    assert any(p["id"] == approval_id for p in pending)

    # Resolve approval
    resolved = temp_db.resolve_pending_approval(
        approval_id=approval_id,
        response="Confirmed by candidate",
        approved=True,
    )
    assert resolved is True

    resolved_list = temp_db.list_pending_approvals(status="approved")
    assert any(p["id"] == approval_id for p in resolved_list)


def test_record_agent_cycle(temp_db: JobAgentStorage):
    cycle_id = "cycle_test_123"
    temp_db.record_agent_cycle(cycle_id=cycle_id, status="running")
    temp_db.record_agent_cycle(
        cycle_id=cycle_id,
        status="completed",
        triage_result={"scanned": 10},
        reports_result={"report": "path.pdf"},
    )
    with temp_db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, triage_result FROM agent_cycles WHERE id = ?", (cycle_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row["status"] == "completed"
        assert "scanned" in row["triage_result"]

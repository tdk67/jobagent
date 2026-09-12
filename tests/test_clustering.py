"""Unit tests for ApplicationClusterer and email threading."""

from pathlib import Path
import pytest
from src.core.storage import JobAgentStorage, UNKNOWN_ROLE
from src.tools.email.adapters import EmailRecord
from src.tools.email.classifier import EmailClassifier
from src.tools.email.clustering import ApplicationClusterer


def test_clustering_merges_multiple_emails_for_same_application(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    db_path = tmp_path / "test_cluster.db"
    storage = JobAgentStorage(db_path=str(db_path))
    clusterer = ApplicationClusterer(storage=storage)

    # Email 1: Confirmation (fictional company Acme Technologies GmbH, role Senior Software Engineer)
    email_1 = EmailRecord(
        entry_id="msg_001",
        sender_name="Acme Technologies GmbH",
        sender_email="recruiting@acme-technologies.de",
        subject="Ihre Bewerbung als Senior Software Engineer bei Acme Technologies GmbH",
        received_time="2026-09-08T10:00:00Z",
        body="Vielen Dank für Ihre Bewerbung als Senior Software Engineer bei der Acme Technologies GmbH.",
    )

    # Email 2: Privacy / GDPR notice (same company Acme Technologies, generic subject)
    email_2 = EmailRecord(
        entry_id="msg_002",
        sender_name="Acme Technologies Datenschutz",
        sender_email="datenschutz@acme-technologies.de",
        subject="Datenschutzhinweise zu Ihrer Bewerbung bei Acme Technologies",
        received_time="2026-09-08T10:05:00Z",
        body="Hinweise zur Verarbeitung Ihrer Daten im Rahmen des Bewerbungsverfahrens.",
    )

    # Email 3: Rejection notice (company Acme Technologies)
    email_3 = EmailRecord(
        entry_id="msg_003",
        sender_name="Acme Technologies HR",
        sender_email="hr@acme-technologies.de",
        subject="Ihre Bewerbung bei Acme Technologies",
        received_time="2026-09-10T14:00:00Z",
        body="Leider müssen wir Ihnen mitteilen, dass wir uns für andere Bewerber entschieden haben.",
    )

    # Process all 3 emails
    summary = clusterer.cluster_batch([email_1, email_2, email_3], folder="Bewerbung")

    # Verify exactly 1 application created in CRM
    apps = storage.list_applications()
    assert len(apps) == 1
    app = apps[0]
    assert app["company"] == "Acme Technologies"  # Legal suffix stripped
    assert app["role"] == "Senior Software Engineer"
    assert app["status"] == "Rejected"  # Status transitioned by rejection

    # Verify all 3 emails are linked to this application
    linked_emails = storage.get_application_emails(app["id"])
    assert len(linked_emails) == 3
    entry_ids = [e["entry_id"] for e in linked_emails]
    assert entry_ids == ["msg_001", "msg_002", "msg_003"]


def test_clustering_rejects_noise_companies(tmp_path: Path):
    db_path = tmp_path / "test_noise.db"
    storage = JobAgentStorage(db_path=str(db_path))
    clusterer = ApplicationClusterer(storage=storage)

    # False positive email with 'h LinkedIn' or 'Apply with LinkedIn'
    email_noise = EmailRecord(
        entry_id="msg_noise_1",
        sender_name="h LinkedIn",
        sender_email="messages-noreply@linkedin.com",
        subject="Bewerben mit LinkedIn: Senior Engineer",
        received_time="2026-09-08T09:00:00Z",
        body="Sie haben sich mit LinkedIn beworben.",
    )

    res = clusterer.process_email(email_noise, folder="Inbox")
    assert res["application_id"] is None

    # Verify NO application was created for LinkedIn
    apps = storage.list_applications()
    assert len(apps) == 0


def test_clustering_role_upgrade(tmp_path: Path):
    """Verifies that an initial placeholder role is upgraded when a specific role is mentioned."""
    db_path = tmp_path / "test_role_upgrade.db"
    storage = JobAgentStorage(db_path=str(db_path))
    clusterer = ApplicationClusterer(storage=storage)

    # Email 1: Generic confirmation with functional suffix in sender_name
    email_1 = EmailRecord(
        entry_id="msg_app_1",
        sender_name="NovaCorp HR",
        sender_email="hr@novacorp.de",
        subject="Eingangsbestätigung: NovaCorp Holding GmbH",
        received_time="2026-09-08T11:00:00Z",
        body="Vielen Dank für Ihre Bewerbung bei NovaCorp Holding GmbH.",
    )
    clusterer.process_email(email_1, folder="Bewerbung")

    # Email 2: Follow-up mentioning exact title
    email_2 = EmailRecord(
        entry_id="msg_app_2",
        sender_name="NovaCorp HR",
        sender_email="hr@novacorp.de",
        subject="Ihre Bewerbung als Lead Software Architect - Cloud & Systems (m/w/d)",
        received_time="2026-09-09T15:00:00Z",
        body="Bezüglich Ihrer Bewerbung als Lead Software Architect bei NovaCorp.",
    )
    clusterer.process_email(email_2, folder="Bewerbung")

    apps = storage.list_applications()
    assert len(apps) == 1
    assert apps[0]["company"] == "NovaCorp"
    assert apps[0]["role"] == "Lead Software Architect - Cloud & Systems"


def test_clustering_preserves_distinct_roles_at_same_company(tmp_path: Path):
    """Verifies that applying to distinct concrete roles at the same company creates separate records."""
    db_path = tmp_path / "test_distinct_roles.db"
    storage = JobAgentStorage(db_path=str(db_path))

    # Application 1: Backend Developer
    app1_id = storage.upsert_application(
        company="GlobalTech GmbH",
        role="Backend Developer",
        applied_date="2026-08-01T10:00:00Z",
    )

    # Application 2: Engineering Manager at same company
    app2_id = storage.upsert_application(
        company="GlobalTech",
        role="Engineering Manager",
        applied_date="2026-08-15T14:00:00Z",
    )

    assert app1_id != app2_id

    apps = storage.list_applications()
    assert len(apps) == 2
    roles = {a["role"] for a in apps}
    assert roles == {"Backend Developer", "Engineering Manager"}

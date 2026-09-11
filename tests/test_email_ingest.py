"""Tests for email ingestion, classification, and triage."""

from pathlib import Path
from src.core.storage import JobAgentStorage
from src.tools.email.adapters import MockEmailAdapter
from src.tools.email.classifier import EmailClassifier
from src.tools.email_ingest_tool import EmailIngestEngine


def test_email_classifier_cases():
    applied = {
        "techcorp": {"company": "TechCorp", "role": "Senior Engineer"},
        "finsoft": {"company": "FinSoft", "role": "Backend Lead"},
    }
    classifier = EmailClassifier(applied_companies=applied)

    # 1. Confirmation
    res_conf = classifier.classify(
        subject="Eingangsbestätigung: Bewerbung als Senior Engineer",
        body="Vielen Dank für Ihre Bewerbung bei TechCorp. Ihre Unterlagen sind eingegangen.",
        sender_name="TechCorp Recruiting",
        sender_email="jobs@techcorp.com",
    )
    assert res_conf.category == "application_confirmation"
    assert res_conf.matched_company == "TechCorp"

    # 2. Rejection
    res_rej = classifier.classify(
        subject="Ihre Bewerbung als Backend Lead",
        body="Leider müssen wir Ihnen mitteilen, dass wir uns für andere Bewerber entschieden haben.",
        sender_name="FinSoft HR",
        sender_email="hr@finsoft.de",
    )
    assert res_rej.category == "rejection"
    assert res_rej.matched_company == "FinSoft"

    # 3. Genuine Interview Invitation
    res_int = classifier.classify(
        subject="Einladung zum Vorstellungsgespräch: TechCorp",
        body="Wir möchten Sie gerne in einem Videointerview persönlich kennenlernen. https://teams.microsoft.com/l/meetup-join/abc999",
        sender_name="TechCorp Talent",
        sender_email="talent@techcorp.com",
    )
    assert res_int.category == "interview_invitation"
    assert res_int.matched_company == "TechCorp"
    assert res_int.meeting_link is not None
    assert "teams.microsoft.com" in res_int.meeting_link

    # 4. Deceptive noise / sales pitch
    res_noise = classifier.classify(
        subject="Exklusives Webinar für Vertrieb und Softwarelösungen",
        body="Melden Sie sich jetzt an für unser Bildungsgutschein Finanzkonzepte Coaching!",
        sender_name="Sales Growth Hub",
        sender_email="promo@growthhub.com",
    )
    assert res_noise.category == "noise"


def test_email_ingest_engine_triage(tmp_path: Path):
    db_path = tmp_path / "test_ingest.db"
    storage = JobAgentStorage(db_path=str(db_path))

    # Pre-populate applied company
    storage.upsert_application(
        company="TechCorp",
        role="Senior Engineer",
        applied_date="2026-09-01T10:00:00Z",
        status="Applied",
    )

    # Mock emails
    mock_data = [
        {
            "entry_id": "msg_001",
            "sender_name": "TechCorp",
            "sender_email": "jobs@techcorp.com",
            "subject": "Einladung zum Vorstellungsgespräch: Senior Engineer",
            "body": "Gerne laden wir Sie zum Vorstellungsgespräch ein: https://meet.google.com/abc-defg-hij",
            "received_time": "2026-09-02T15:30:00Z",
        },
        {
            "entry_id": "msg_002",
            "sender_name": "Spam Vendor",
            "sender_email": "sales@vendor.com",
            "subject": "Gratis Webinar für Vertrieb!",
            "body": "Steigern Sie Ihren Umsatz mit unserer Softwarelösung.",
            "received_time": "2026-09-03T09:00:00Z",
        },
    ]

    mock_adapter = MockEmailAdapter(mock_data)
    engine = EmailIngestEngine(storage=storage, adapters=[mock_adapter])

    results = engine.run_triage(limit=10)
    assert results["total_scanned"] == 2
    assert results["interviews_found"] == 1
    assert results["noise_filtered"] == 1
    assert len(results["actionable_alerts"]) == 1
    assert results["actionable_alerts"][0]["company"] == "TechCorp"

    # Verify database updated
    interviews = storage.list_interviews()
    assert len(interviews) == 1
    assert interviews[0]["company"] == "TechCorp"

    # Verify application status transitioned to Interview
    app = storage.get_application_by_company("TechCorp")
    assert app["status"] == "Interview"


def test_interview_date_extraction(tmp_path: Path):
    db_path = tmp_path / "test_dates.db"
    storage = JobAgentStorage(db_path=str(db_path))

    classifier = EmailClassifier()
    res = classifier.classify(
        subject="Einladung zum Vorstellungsgespräch",
        body="Gerne laden wir Sie am 18.09.2026 um 10:30 Uhr zu einem Vorstellungsgespräch ein.",
    )
    assert res.category == "interview_invitation"
    assert res.suggested_date is not None
    assert "18.09.2026" in res.suggested_date

    # Verify ingest engine records the extracted date instead of receipt time
    mock_adapter = MockEmailAdapter([
        {
            "entry_id": "msg_interview",
            "sender_name": "Cloud Corp",
            "sender_email": "jobs@cloudcorp.de",
            "subject": "Vorstellungsgespräch: Cloud Corp",
            "body": "Termin ist am 20.09.2026 um 15:00 Uhr via Teams: https://teams.microsoft.com/l/meetup-join/123",
            "received_time": "2026-09-01T08:00:00Z",
        }
    ])
    engine = EmailIngestEngine(storage=storage, adapters=[mock_adapter])
    results = engine.run_triage()
    assert results["interviews_found"] == 1

    interviews = storage.list_interviews()
    assert len(interviews) == 1
    # Must match the date scheduled in the body, not the received_time (2026-09-01)
    assert "20.09.2026" in interviews[0]["interview_date"]


def test_anti_phishing_unverified_sender():
    """Verifies that an email mentioning a tracked company from an unverified sender domain is rejected as an interview (C1)."""
    applied = {"chrono24": {"company": "Chrono24", "role": "Senior Java Developer"}}
    classifier = EmailClassifier(applied_companies=applied)

    # Attacker tries to impersonate Chrono24 from an untrusted domain with malicious link
    res = classifier.classify(
        subject="Interview Invitation: Chrono24 Developer",
        body="Dear candidate, Chrono24 has selected your profile for an interview: http://phish-site.com/join",
        sender_name="Recruiter",
        sender_email="attacker@random-domain.xyz",
    )

    # Must NOT be classified as interview_invitation because sender domain is unverified
    assert res.category != "interview_invitation"
    assert res.category == "follow_up"
    assert res.confidence < 0.50
    # Insecure and untrusted link must be stripped
    assert res.meeting_link is None


def test_meeting_link_security_validation():
    """Verifies that meeting links must use HTTPS and belong to strictly trusted video platforms (C1)."""
    classifier = EmailClassifier()

    # 1. Untrusted domain should be rejected
    res_fake = classifier.classify(
        subject="Interview",
        body="Join meeting at https://teams.microsoft.com.attacker.com/join",
        sender_email="recruiting@company.com",
    )
    assert res_fake.meeting_link is None

    # 2. Insecure HTTP should be rejected
    res_http = classifier.classify(
        subject="Interview",
        body="Join meeting at http://teams.microsoft.com/l/meetup-join/123",
        sender_email="recruiting@company.com",
    )
    assert res_http.meeting_link is None

    # 3. Trusted platforms (Teams, Zoom, Google Meet) should be accepted
    res_teams = classifier.classify(
        subject="Interview",
        body="Join: https://teams.microsoft.com/l/meetup-join/12345",
        sender_email="recruiting@company.com",
    )
    assert res_teams.meeting_link == "https://teams.microsoft.com/l/meetup-join/12345"

    res_meet = classifier.classify(
        subject="Interview",
        body="Join: https://meet.google.com/abc-defg-hij",
        sender_email="recruiting@company.com",
    )
    assert res_meet.meeting_link == "https://meet.google.com/abc-defg-hij"


def test_idempotent_interview_and_email_ingest(tmp_path: Path):
    """Verifies that repeated triage cycles do not create duplicate interviews or interactions (H1)."""
    db_path = tmp_path / "test_idempotent.db"
    storage = JobAgentStorage(db_path=str(db_path))

    storage.upsert_application(
        company="Chrono24",
        role="Senior Java Developer",
        applied_date="2026-09-02T10:00:00Z",
        status="Applied",
    )

    mock_email = [
        {
            "entry_id": "unique-msg-id-12345",
            "sender_name": "Chrono24 Recruiting",
            "sender_email": "jobs@chrono24.com",
            "subject": "Vorstellungsgespräch: Senior Java Developer",
            "body": "Gerne laden wir Sie am 25.09.2026 um 14:00 Uhr ein: https://teams.microsoft.com/l/meetup-join/555",
            "received_time": "2026-09-04T12:00:00Z",
        }
    ]

    mock_adapter = MockEmailAdapter(mock_email)
    engine = EmailIngestEngine(storage=storage, adapters=[mock_adapter])

    # Run cycle 1
    res1 = engine.run_triage()
    assert res1["interviews_found"] == 1
    assert len(storage.list_interviews()) == 1
    assert len(res1["actionable_alerts"]) == 1

    # Run cycle 2 with identical inbox state
    res2 = engine.run_triage()
    # Database MUST NOT contain duplicate interviews
    assert len(storage.list_interviews()) == 1
    assert storage.list_interviews()[0]["entry_id"] == "unique-msg-id-12345"
    # H5: Alert must NOT re-fire for already recorded interview
    assert len(res2["actionable_alerts"]) == 0

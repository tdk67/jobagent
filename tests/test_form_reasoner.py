"""Unit tests for JobAgent Form Reasoner, continuous learning, and QA memory."""

from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from src.a2a.server import create_a2a_app
from src.core.config import AppConfig
from src.core.profile import CandidateProfile, PersonalInfo, Preferences, TechnicalSkills
from src.core.storage import JobAgentStorage
from src.tools.form.reasoner import FormReasoner


@pytest.fixture
def temp_db(tmp_path: Path) -> JobAgentStorage:
    db_file = tmp_path / "test_qa.db"
    return JobAgentStorage(str(db_file))


@pytest.fixture
def mock_profile() -> CandidateProfile:
    return CandidateProfile(
        personal=PersonalInfo(
            fullName="Erika Mustermann",
            email="erika.mustermann@example.de",
            phone="+49 170 1234567",
            address="Munich, Germany",
            salaryExpectation="95.000 €",
            noticePeriod="3 months",
            linkedinUrl="https://linkedin.com/in/erika-mustermann",
            githubUrl="https://github.com/erika-mustermann",
        ),
        technical_skills=TechnicalSkills(
            core=["Java", "Spring Boot", "AWS"],
            yearsExperience={"Java": 8, "Spring Boot": 6},
        ),
        preferences=Preferences(
            workModel="Hybrid or Remote",
            targetRoles=["Senior Java Developer"],
        ),
        common_answers={
            "Do you require visa sponsorship?": "No, I am an EU Citizen.",
            "Sind Sie berechtigt, in Deutschland zu arbeiten?": "Ja, uneingeschränkte Arbeitserlaubnis.",
        },
    )


def test_qa_memory_crud(temp_db: JobAgentStorage, mock_profile: CandidateProfile):
    # Test normalization
    norm = temp_db.normalize_question("  Wie viele Jahre Erfahrung haben Sie mit Java???  ")
    assert norm == "wie viele jahre erfahrung haben sie mit java"

    # Test save and retrieve
    temp_db.save_qa_answer("Wann können Sie starten?", "Zum nächsten Monatsersten", category="general")
    ans = temp_db.get_qa_answer("Wann können Sie starten?")
    assert ans == "Zum nächsten Monatsersten"

    # Test fuzzy substring lookup
    ans_fuzzy = temp_db.get_qa_answer("Bitte geben Sie an: Wann können Sie starten?")
    assert ans_fuzzy == "Zum nächsten Monatsersten"

    # Test seed from profile
    temp_db.seed_qa_from_profile(mock_profile)
    visa_ans = temp_db.get_qa_answer("Do you require visa sponsorship?")
    assert visa_ans == "No, I am an EU Citizen."


def test_form_reasoner_core_bilingual(temp_db: JobAgentStorage, mock_profile: CandidateProfile):
    reasoner = FormReasoner(storage=temp_db, profile=mock_profile)

    fields = [
        {"fieldId": "f1", "label": "Vorname", "type": "text"},
        {"fieldId": "f2", "label": "Last Name", "type": "text"},
        {"fieldId": "f3", "label": "E-Mail-Adresse", "type": "email"},
        {"fieldId": "f4", "label": "Contact Phone", "type": "tel"},
        {"fieldId": "f5", "label": "Gehaltserwartung (brutto/Jahr)", "type": "text"},
        {"fieldId": "f6", "label": "Notice Period / Earliest Start", "type": "text"},
        {"fieldId": "f7", "label": "GitHub Profile", "type": "text"},
    ]

    res = reasoner.reason_form(fields)
    assert res["total_fields"] == 7
    assert res["mapped_fields"] == 7

    mappings = res["mappings"]
    assert mappings["f1"] == "Erika"
    assert mappings["f2"] == "Mustermann"
    assert mappings["f3"] == "erika.mustermann@example.de"
    assert mappings["f4"] == "+49 170 1234567"
    assert mappings["f5"] == "95.000 €"
    assert mappings["f6"] == "3 months"
    assert mappings["f7"] == "https://github.com/erika-mustermann"


def test_form_reasoner_select_options_matching(temp_db: JobAgentStorage, mock_profile: CandidateProfile):
    reasoner = FormReasoner(storage=temp_db, profile=mock_profile)

    # Save custom answer
    temp_db.save_qa_answer("Arbeitserlaubnis für Deutschland", "Ja", category="compliance")

    fields = [
        {
            "fieldId": "select_work_auth",
            "label": "Arbeitserlaubnis für Deutschland",
            "type": "select-one",
            "options": [
                {"value": "no", "text": "Nein, Visum erforderlich"},
                {"value": "yes", "text": "Ja, uneingeschränkt vorhanden"},
            ],
        }
    ]

    res = reasoner.reason_form(fields)
    assert res["mapped_fields"] == 1
    # Option with 'Ja' text or value should match
    assert res["mappings"]["select_work_auth"] == "yes"


def test_server_form_endpoints(tmp_path: Path, mock_profile: CandidateProfile):
    db_file = tmp_path / "server_test.db"
    storage = JobAgentStorage(str(db_file))
    cfg = AppConfig()
    cfg.storage.database_path = str(db_file)

    app = create_a2a_app(config=cfg, storage=storage, profile=mock_profile, api_token="test-token-123")
    # Loopback base_url: F3 gateway validates the Host header on /api/* routes
    # (TestClient's default 'testserver' is correctly rejected).
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    headers = {"Authorization": "Bearer test-token-123"}

    # 1. Test POST /api/v1/form/learn
    learn_res = client.post(
        "/api/v1/form/learn",
        headers=headers,
        json={"question": "Preferred IDE", "answer": "IntelliJ IDEA", "category": "tools"},
    )
    assert learn_res.status_code == 200
    assert learn_res.json()["saved"] is True

    # 2. Test GET /api/v1/form/memory
    mem_res = client.get("/api/v1/form/memory", headers=headers)
    assert mem_res.status_code == 200
    entries = mem_res.json()["memory"]
    assert any(e["question_text"] == "Preferred IDE" for e in entries)

    # 3. Test POST /api/v1/form/reason picks up learned question
    reason_res = client.post(
        "/api/v1/form/reason",
        headers=headers,
        json={
            "url": "https://example.com/apply",
            "fields": [
                {"fieldId": "f_name", "label": "Full Name", "type": "text"},
                {"fieldId": "f_ide", "label": "What is your preferred IDE?", "type": "text"},
            ],
        },
    )
    assert reason_res.status_code == 200
    data = reason_res.json()
    assert data["mappings"]["f_name"] == "Erika Mustermann"
    assert data["mappings"]["f_ide"] == "IntelliJ IDEA"


def test_qa_memory_no_false_positive_substrings(temp_db: JobAgentStorage):
    """Verifies that short characters or substrings do NOT falsely match long QA memory answers (C4)."""
    temp_db.save_qa_answer("What is your expected salary?", "95,000 EUR", "compensation")

    # 1. Single character searches must return None
    assert temp_db.get_qa_answer("a") is None
    assert temp_db.get_qa_answer("e") is None
    assert temp_db.get_qa_answer("x") is None

    # 2. Short sub-word fragments must not match unless full words
    assert temp_db.get_qa_answer("sal") is None
    assert temp_db.get_qa_answer("exp") is None

    # 3. Valid queries should match
    assert temp_db.get_qa_answer("expected salary") == "95,000 EUR"
    assert temp_db.get_qa_answer("What is your expected salary?") == "95,000 EUR"


def test_form_reasoner_passwords_and_security(temp_db: JobAgentStorage, mock_profile: CandidateProfile):
    """Verifies that password fields are never autofilled and sensitive fields require user confirmation (C3)."""
    reasoner = FormReasoner(storage=temp_db, profile=mock_profile)

    fields = [
        {"fieldId": "pwd1", "label": "Password", "type": "password"},
        {"fieldId": "pwd2", "label": "Confirm Password", "type": "password"},
        {"fieldId": "auth", "label": "Do you have valid work authorization for Germany?", "type": "text"},
    ]

    res = reasoner.reason_form(fields)
    mappings = res.get("mappings", {})

    # Password fields MUST NEVER be populated
    assert "pwd1" not in mappings
    assert "pwd2" not in mappings

    # Work authorization matched
    assert "auth" in mappings
    assert "Ja" in mappings["auth"] or "Arbeitserlaubnis" in mappings["auth"] or "EU Citizen" in mappings["auth"]


def test_form_reasoner_city_field_maps_to_city_not_street(temp_db: JobAgentStorage):
    """F4 VP1: a field labeled 'City'/'Ort'/'Stadt' must map to profile.personal.city
    (e.g. 'Frankfurt am Main'), NOT the street (the first address segment)."""
    profile = CandidateProfile(
        personal=PersonalInfo(
            fullName="Jane Doe",
            email="jane.doe@example.com",
            phone="+49 150 0000000",
            street="Musterstrasse 1",
            city="Frankfurt am Main",
            postalCode="60311",
            address="Musterstrasse 1, 60311 Frankfurt am Main, Deutschland",
        )
    )
    reasoner = FormReasoner(storage=temp_db, profile=profile)

    for label in ["City", "Ort", "Stadt", "Wohnort"]:
        res = reasoner.reason_form([{"fieldId": f"f_{label}", "label": label, "type": "text"}])
        assert res["mapped_fields"] == 1, f"label {label!r} not mapped"
        assert res["mappings"][f"f_{label}"] == "Frankfurt am Main", f"label {label!r} -> {res['mappings'][f'f_{label}']!r}"


def test_form_reasoner_city_falls_back_to_postal_segment(temp_db: JobAgentStorage):
    """F4 VP1: without an explicit pers.city, the reasoner falls back to the address
    segment containing the postal code — NOT segment 0 (the street)."""
    profile = CandidateProfile(
        personal=PersonalInfo(
            fullName="Jane Doe",
            email="jane.doe@example.com",
            address="Musterstrasse 1, 60311 Frankfurt am Main, Deutschland",
            city=None,
        )
    )
    reasoner = FormReasoner(storage=temp_db, profile=profile)

    res = reasoner.reason_form([{"fieldId": "f_city", "label": "City", "type": "text"}])
    assert res["mappings"]["f_city"] == "Frankfurt am Main", res["mappings"]["f_city"]


def test_form_reasoner_capgemini_edge_cases(temp_db: JobAgentStorage):
    """Verifies resolution of language level (B2 not C1), standort (not street), and compliance dropdowns."""
    profile = CandidateProfile(
        personal=PersonalInfo(
            fullName="Alex Example",
            email="alex.example@example.com",
            phone="+49 1511 000 0000",
            street="Hauptstr. 10",
            city="Darmstadt",
            countryDe="Deutschland",
            countryEn="Germany",
            address="Hauptstr. 10, 64283 Darmstadt, Deutschland",
        ),
        preferences=Preferences(
            locations=["Frankfurt", "Darmstadt"],
        ),
        languages={
            "german": "B2 - selbstständige Sprachverwendung",
            "english": "C1 - fachkundige Sprachkenntnisse",
            "hungarian": "Muttersprache",
        },
    )
    reasoner = FormReasoner(storage=temp_db, profile=profile)

    fields = [
        # 1. German language level: Must pick B2 option, NEVER C1/C2!
        {
            "fieldId": "f_german",
            "label": "1. *Wie gut sind deine Deutschkenntnisse",
            "type": "radio",
            "options": [
                {"value": "0", "text": "Keine - No Skills"},
                {"value": "1", "text": "A1 - Grundkenntnisse"},
                {"value": "2", "text": "A2 - Erweiterte Grundkenntnisse"},
                {"value": "3", "text": "B1 - Gute Sprachkenntnisse"},
                {"value": "4", "text": "B2 - Fließende Sprachkenntnisse"},
                {"value": "5", "text": "C1 / C2 - Verhandlungssichere Sprachkenntnisse"},
            ],
        },
        # 2. Location preference: Must pick target location (Frankfurt), NOT street address!
        {
            "fieldId": "f_standort",
            "label": "2. *Für welchen Standort möchtest du dich primär bewerben?",
            "type": "textarea",
        },
        # 3. Country of residence dropdown
        {
            "fieldId": "f_residence",
            "label": "Land des aktuellen Wohnsitzes*",
            "type": "select",
            "options": [
                {"value": "-1", "text": "Keine Auswahl"},
                {"value": "DE", "text": "Deutschland"},
                {"value": "FR", "text": "Frankreich"},
            ],
        },
        # 4. Work authorization dropdown
        {
            "fieldId": "f_work_auth",
            "label": "Hast du eine Arbeitserlaubnis in dem Land, in dem du dich bewirbst?*",
            "type": "select",
            "options": [
                {"value": "", "text": "Keine Auswahl"},
                {"value": "true", "text": "Ja"},
                {"value": "false", "text": "Nein"},
            ],
        },
        # 5. Prior employment dropdown
        {
            "fieldId": "f_prev_employed",
            "label": "Warst du bereits bei der Capgemini Gruppe angestellt?*",
            "type": "select",
            "options": [
                {"value": "", "text": "Keine Auswahl"},
                {"value": "true", "text": "Ja"},
                {"value": "false", "text": "Nein"},
            ],
        },
    ]

    res = reasoner.reason_form(fields)
    mappings = res["mappings"]

    # Assert German is B2 (value "4"), NOT C1/C2 (value "5")
    assert mappings["f_german"] == "4"

    # Assert Standort is Frankfurt, NOT street address
    assert mappings["f_standort"] == "Frankfurt"
    assert "Hauptstr" not in mappings["f_standort"]

    # Assert Country of residence is DE
    assert mappings["f_residence"] == "DE"

    # Assert Work authorization is true (Ja)
    assert mappings["f_work_auth"] == "true"

    # Assert Prior employment is false (Nein)
    assert mappings["f_prev_employed"] == "false"


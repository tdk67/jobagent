"""Tests for intelligent role extraction."""

from src.tools.role_extractor import RoleExtractor, extract_role_from_context


def test_role_extractor_german_patterns():
    extractor = RoleExtractor()
    assert extractor.extract_role("Bewerbung als Senior Cloud Architect", use_llm=False) == "Senior Cloud Architect"
    assert extractor.extract_role("Ihre Bewerbung für die Position: Principal Engineer", use_llm=False) == "Principal Engineer"
    assert extractor.extract_role("Einladung für die Stelle Lead Developer", use_llm=False) == "Lead Developer"


def test_role_extractor_english_patterns():
    extractor = RoleExtractor()
    assert extractor.extract_role("Application for Senior Python Engineer", use_llm=False) == "Senior Python Engineer"
    assert extractor.extract_role("Interview regarding Role: Staff DevOps Engineer", use_llm=False) == "Staff DevOps Engineer"
    assert extractor.extract_role("Your application as a Data Scientist", use_llm=False) == "Data Scientist"


def test_role_extractor_non_role_filtering():
    extractor = RoleExtractor()
    # Coaching and webinar emails should be rejected
    assert extractor.extract_role("Exklusives Webinar für die Positionierung am Markt", use_llm=False) is None
    assert extractor.extract_role("Bewerbungstraining und Coaching für Sie", use_llm=False) is None
    assert extractor.extract_role("Keine Position erkennbar", use_llm=False) is None
    assert extractor.extract_role("JobAlert: Neue Angebote", use_llm=False) is None

"""Tests for company and role normalization and noise rejection."""

import pytest
from src.tools.email.normalizer import (
    is_noise_company,
    normalize_company_name,
    normalize_role_title,
)


def test_is_noise_company():
    # Noise aggregators and email addresses
    assert is_noise_company("LinkedIn") is True
    assert is_noise_company("h LinkedIn") is True
    assert is_noise_company("Apply With LinkedIn") is True
    assert is_noise_company("notifications@app.bamboohr.com") is True
    assert is_noise_company("join.com") is True
    assert is_noise_company("noreply") is True
    assert is_noise_company("Recruiting-Team") is True
    assert is_noise_company("Candidate") is True
    assert is_noise_company("") is True
    assert is_noise_company(None) is True

    assert is_noise_company("E+cgd1bocgveo4o4pp.circula@recruitee-email.com") is True
    assert is_noise_company("Uns eingegangen") is True
    assert is_noise_company("ist eingegangen") is True

    # Genuine companies
    assert is_noise_company("Ratbacher") is False
    assert is_noise_company("Ratbacher GmbH") is False
    assert is_noise_company("Chrono24") is False
    assert is_noise_company("Appian") is False
    assert is_noise_company("Kardex") is False
    assert is_noise_company("trendtours Holding GmbH") is False
    assert is_noise_company("Auto-Nix") is False


def test_normalize_company_name():
    assert normalize_company_name("Ratbacher GmbH") == "Ratbacher"
    assert normalize_company_name("Ratbacher") == "Ratbacher"
    assert normalize_company_name("trendtours Holding GmbH") == "Trendtours"
    assert normalize_company_name("Trendtours") == "Trendtours"
    assert normalize_company_name("Appian Corporation") == "Appian"
    assert normalize_company_name("Appian") == "Appian"
    assert normalize_company_name("ITSG GmbH") == "ITSG"
    assert normalize_company_name("ITSG") == "ITSG"
    assert normalize_company_name("DFV Deutsche Familienversicherung AG") == "Deutsche Familienversicherung"
    assert normalize_company_name("Deutschen Familienversicherung") == "Deutsche Familienversicherung"
    assert normalize_company_name("ALD Vacuum Technologies GmbH") == "ALD Vacuum Technologies"
    assert normalize_company_name("HMS-Recruit-no-reply") == "HMS Networks"
    assert normalize_company_name("DekaBank Deutsche Girozentrale ist eingegangen") == "DekaBank"
    assert normalize_company_name("Webmailer Amadeus Fire") == "Amadeus Fire"
    assert normalize_company_name("dwpbank als") == "dwpbank"


def test_normalize_role_title():
    # Placeholders should return None
    assert normalize_role_title("Candidate") is None
    assert normalize_role_title("Bewerber") is None
    assert normalize_role_title("Apply With LinkedIn") is None
    assert normalize_role_title("") is None
    assert normalize_role_title(None) is None

    # Cleaning leading prepositions and noise
    assert normalize_role_title("of Senior Backend Engineer - Germany") == "Senior Backend Engineer"
    assert normalize_role_title("r Stelle: Senior Java Software Entwickler") == "Senior Java Software Entwickler"
    assert normalize_role_title("Software Quality Lead - QA & Test Management (m/w/d)") == "Software Quality Lead - QA & Test Management"
    assert normalize_role_title("AI Solution Engineer (all genders)") == "AI Solution Engineer"

"""Unit and integration tests for Cover Letter Generation Engine (DIN 5008)."""

from pathlib import Path
from src.core.profile import CandidateProfile, PersonalInfo, DocumentPaths
from src.tools.cover_letter_tool import CoverLetterEngine


def test_cover_letter_generation_german_and_english(tmp_path: Path):
    out_dir = tmp_path / "cover_letters"
    engine = CoverLetterEngine(output_dir=out_dir)

    prof = CandidateProfile(
        personal=PersonalInfo(
            fullName="Jane Doe",
            street="Musterstrasse 1",
            postalCode="60311",
            city="Frankfurt am Main",
            email="jane.doe@example.com",
            phone="+49 150 0000000",
            summaryDe="Erfahrene Senior Softwareentwicklerin mit Schwerpunkt auf verteilten Systemen.",
        ),
        documents=DocumentPaths(
            germanCv="C:\\data\\work\\Lebenslauf_JaneDoe_Beispiel.pdf",
            englishCv="C:\\data\\work\\cv_jane_doe_example.pdf",
        ),
    )

    # 1. German Cover Letter
    res_de = engine.generate(
        company="Capgemini",
        role="Senior Java / Cloud Engineer",
        lang="de",
        use_gemini=False,  # deterministic template test
        profile=prof,
    )

    assert Path(res_de["html_path"]).exists()
    assert Path(res_de["pdf_path"]).exists()
    assert Path(res_de["pdf_path"]).stat().st_size > 1000

    html_de_content = Path(res_de["html_path"]).read_text(encoding="utf-8")
    assert "Jane Doe" in html_de_content
    assert "Capgemini" in html_de_content
    assert "Senior Java / Cloud Engineer" in html_de_content
    assert "Bewerbung als Senior Java / Cloud Engineer" in html_de_content
    assert "Mit freundlichen Grüßen," in html_de_content
    assert "Musterstrasse 1" in html_de_content

    # 2. English Cover Letter
    res_en = engine.generate(
        company="Ericsson",
        role="Principal Backend Engineer",
        lang="en",
        use_gemini=False,
        profile=prof,
    )

    assert Path(res_en["html_path"]).exists()
    assert Path(res_en["pdf_path"]).exists()
    assert Path(res_en["pdf_path"]).stat().st_size > 1000

    html_en_content = Path(res_en["html_path"]).read_text(encoding="utf-8")
    assert "Jane Doe" in html_en_content
    assert "Ericsson" in html_en_content
    assert "Principal Backend Engineer" in html_en_content
    assert "Application for Principal Backend Engineer" in html_en_content
    assert "Sincerely," in html_en_content


def test_cover_letter_html_injection_prevention(tmp_path: Path):
    out_dir = tmp_path / "cover_letters_sec"
    engine = CoverLetterEngine(output_dir=out_dir)

    prof = CandidateProfile(
        personal=PersonalInfo(
            fullName="Jane <script>alert(1)</script> Doe",
            street="Musterstrasse 1",
            postalCode="60311",
            city="Frankfurt am Main",
            email="jane.doe@example.com",
            phone="+49 150 0000000",
        ),
        documents=DocumentPaths(
            germanCv="C:\\data\\work\\cv.pdf",
        ),
    )

    res = engine.generate(
        company="EvilCorp <img src=x onerror=alert(2)>",
        role="Hacker & Lead <script>alert(3)</script>",
        lang="de",
        use_gemini=False,
        profile=prof,
    )

    html_content = Path(res["html_path"]).read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html_content
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_content
    assert "<img src=x onerror=alert(2)>" not in html_content
    assert "&lt;img src=x onerror=alert(2)&gt;" in html_content
    assert "<script>alert(3)</script>" not in html_content
    assert "&lt;script&gt;alert(3)&lt;/script&gt;" in html_content
    assert "Hacker &amp; Lead" in html_content


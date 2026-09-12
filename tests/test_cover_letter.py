"""Unit and integration tests for Cover Letter Generation Engine (DIN 5008).

Verifies fail-loud error reporting (no silent generic boilerplate fallbacks)
and secure DIN 5008 PDF rendering.
"""

from pathlib import Path
from unittest.mock import patch
import pytest

from src.core.profile import CandidateProfile, PersonalInfo, DocumentPaths
from src.tools.cover_letter_tool import CoverLetterEngine, CoverLetterGenerationError


def test_cover_letter_generation_with_body_text(tmp_path: Path):
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

    custom_de_body = (
        "Sehr geehrte Damen und Herren,\n\n"
        "mit über 8 Jahren Erfahrung in verteilten Systemen und Cloud-Architekturen bewerbe ich mich für die Position "
        "als Senior Java / Cloud Engineer bei Capgemini.\n\n"
        "In meiner bisherigen Laufbahn habe ich hochverfügbare Microservice-Plattformen skaliert und Teams technisch geleitet."
    )

    # 1. German Cover Letter with tailored body
    res_de = engine.generate(
        company="Capgemini",
        role="Senior Java / Cloud Engineer",
        lang="de",
        body_text=custom_de_body,
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
    assert "über 8 Jahren Erfahrung in verteilten Systemen" in html_de_content

    # 2. English Cover Letter with mocked Gemini generation
    mock_en_body = (
        "Dear Hiring Team,\n\n"
        "I am writing to express my strong interest in the Principal Backend Engineer role at Ericsson. "
        "With a proven track record in high-throughput distributed architectures, I have led backend initiatives "
        "powering millions of transactions daily."
    )

    with patch("src.tools.cover_letter_tool.call_gemini_semantic_analysis", return_value=mock_en_body):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key-mock"}):
            res_en = engine.generate(
                company="Ericsson",
                role="Principal Backend Engineer",
                lang="en",
                use_gemini=True,
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
    assert "proven track record in high-throughput distributed architectures" in html_en_content


def test_cover_letter_fails_loud_without_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    out_dir = tmp_path / "cover_letters_err"
    engine = CoverLetterEngine(output_dir=out_dir)

    prof = CandidateProfile(
        personal=PersonalInfo(fullName="Jane Doe", email="jane@example.com")
    )

    # Ensure GEMINI_API_KEY is not set
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(CoverLetterGenerationError) as exc_info:
        engine.generate(
            company="Acme Corp",
            role="Lead Engineer",
            use_gemini=True,
            profile=prof,
        )

    assert "GEMINI_API_KEY is not configured" in str(exc_info.value)


def test_cover_letter_fails_loud_on_429_quota_limit(tmp_path: Path):
    out_dir = tmp_path / "cover_letters_err2"
    engine = CoverLetterEngine(output_dir=out_dir)
    prof = CandidateProfile(personal=PersonalInfo(fullName="Jane Doe"))

    with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
        with patch("src.tools.cover_letter_tool.call_gemini_semantic_analysis", side_effect=Exception("HTTP 429 RESOURCE_EXHAUSTED Quota exceeded")):
            with pytest.raises(CoverLetterGenerationError) as exc_info:
                engine.generate(
                    company="Acme Corp",
                    role="Lead Engineer",
                    use_gemini=True,
                    profile=prof,
                )

            assert "429" in str(exc_info.value)
            assert "quota exceeded or rate-limited" in str(exc_info.value)


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

    safe_body = "Bewerbungstext ohne Skripte <script>alert('body')</script> mit Qualifikationen."

    res = engine.generate(
        company="EvilCorp <img src=x onerror=alert(2)>",
        role="Hacker & Lead <script>alert(3)</script>",
        lang="de",
        body_text=safe_body,
        profile=prof,
    )

    html_content = Path(res["html_path"]).read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html_content
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_content
    assert "<img src=x onerror=alert(2)>" not in html_content
    assert "&lt;img src=x onerror=alert(2)&gt;" in html_content
    assert "<script>alert(3)</script>" not in html_content
    assert "&lt;script&gt;alert(3)&lt;/script&gt;" in html_content
    assert "<script>alert('body')</script>" not in html_content
    assert "&lt;script&gt;alert(&#x27;body&#x27;)&lt;/script&gt;" in html_content


def test_cover_letter_dynamic_prompt_includes_job_description_and_cv(tmp_path: Path):
    out_dir = tmp_path / "cover_letters_dynamic"
    engine = CoverLetterEngine(output_dir=out_dir)

    prof = CandidateProfile(
        personal=PersonalInfo(fullName="Tamas Deak", email="tamas@example.com")
    )

    captured_prompts = []

    def mock_gemini(prompt: str, **kwargs):
        captured_prompts.append(prompt)
        return "Sehr geehrte Damen und Herren,\n\nich bewerbe mich hiermit für die Position bei Capgemini.\n\nMit freundlichen Grüßen,\nTamas Deak"

    with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
        with patch("src.tools.cover_letter_tool.call_gemini_semantic_analysis", side_effect=mock_gemini):
            res = engine.generate(
                company="Capgemini",
                role="Senior Software Engineer Defense",
                lang="de",
                job_description="Must have 10+ years experience in Python, distributed backend architectures, and Linux systems.",
                cv_text="25+ years software engineering experience, backend architecture, Python, cloud services.",
                profile=prof,
            )

    assert len(captured_prompts) == 1
    prompt_text = captured_prompts[0]
    # Check that job description and CV context were injected into prompt
    assert "Senior Software Engineer Defense" in prompt_text
    assert "10+ years experience in Python" in prompt_text
    assert "25+ years software engineering experience" in prompt_text
    # Check that static template files do not exist
    root_dir = Path(__file__).resolve().parent.parent
    assert not (root_dir / "templates" / "cover_letter" / "cover_letter_default.de.txt").exists()
    assert not (root_dir / "templates" / "cover_letter" / "cover_letter_default.en.txt").exists()


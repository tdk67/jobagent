"""Tests for report rendering and PDF generation."""

from pathlib import Path
from src.core.profile import CandidateProfile, PersonalInfo
from src.core.storage import JobAgentStorage
from src.tools.report.generator import ReportGenerator
from src.tools.report_render_tool import ReportRenderEngine


def test_report_generator_html_and_pdf(tmp_path: Path):
    gen = ReportGenerator(template_dir="templates", output_dir=str(tmp_path / "output"))

    data = {
        "candidate_name": "Test Candidate",
        "generated_at": "10.09.2026 16:00",
        "statistics": {
            "total_applications": 3,
            "total_interviews": 1,
            "total_rejections": 1,
            "total_pending": 1,
            "response_rate_percent": 33.3,
            "rejection_rate_percent": 33.3,
        },
        "applications": [
            {
                "index": 1,
                "company": "CloudTech AG",
                "role": "Lead Architect",
                "applied_date": "01.09.2026",
                "source": "LinkedIn",
                "location": "Frankfurt am Main",
                "status": "Interview",
            }
        ],
        "total_count": 1,
    }

    # 1. Dashboard
    dash_html = gen.render_html("dashboard", data)
    assert Path(dash_html).exists()
    assert "CloudTech AG" in Path(dash_html).read_text(encoding="utf-8")

    dash_pdf = gen.convert_html_to_pdf(dash_html, "dashboard_test.pdf")
    assert Path(dash_pdf).exists()
    assert Path(dash_pdf).stat().st_size > 1000

    # 2. German AfA Table
    afa_html = gen.render_html("afa_table", data)
    assert Path(afa_html).exists()
    assert "Nachweis über Eigenbemühungen" in Path(afa_html).read_text(encoding="utf-8")

    afa_pdf = gen.convert_html_to_pdf(afa_html, "afa_test.pdf", landscape=True)
    assert Path(afa_pdf).exists()
    assert Path(afa_pdf).stat().st_size > 1000


def test_report_render_engine_integration(tmp_path: Path):
    db_path = tmp_path / "test_report.db"
    storage = JobAgentStorage(db_path=str(db_path))

    storage.upsert_application(
        company="Enterprise AI Corp",
        role="Senior AI Engineer",
        applied_date="2026-09-05T12:00:00Z",
        status="Interview",
    )

    profile = CandidateProfile(
        personal=PersonalInfo(
            fullName="Taylor Swift Developer",
            email="taylor@example.com",
        )
    )

    engine = ReportRenderEngine(storage=storage, profile=profile)
    engine.generator.output_dir = tmp_path / "output_engine"
    engine.generator.output_dir.mkdir(parents=True, exist_ok=True)

    results = engine.generate_all_views()
    assert "dashboard" in results
    assert "afa_table" in results
    assert "agency_summary" in results

    assert Path(results["dashboard"]["html_path"]).exists()
    assert Path(results["dashboard"]["pdf_path"]).exists()
    assert Path(results["afa_table"]["pdf_path"]).exists()


def test_report_engine_date_filtering_and_weekly(tmp_path: Path):
    db_path = tmp_path / "test_dates.db"
    storage = JobAgentStorage(db_path=str(db_path))

    # Insert items across different months: July, August, September
    storage.upsert_application(company="July Tech", role="Dev", applied_date="2026-07-02T10:00:00Z", status="Pending")
    storage.upsert_application(company="Aug Tech", role="Dev", applied_date="2026-08-15T10:00:00Z", status="Pending")
    storage.upsert_application(company="Sept Tech", role="Dev", applied_date="2026-09-02T10:00:00Z", status="Interview")

    profile = CandidateProfile(personal=PersonalInfo(fullName="Test User"))
    engine = ReportRenderEngine(storage=storage, profile=profile)
    engine.generator.output_dir = tmp_path / "output_weekly"
    engine.generator.output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Test date range from 1-Jul to 31-Jul
    jul_res = engine.generate(view_type="afa_table", start_date="1-Jul", end_date="31-Jul-2026")
    assert jul_res["applications_count"] == 1
    assert "July Tech" in Path(jul_res["html_path"]).read_text(encoding="utf-8")
    assert "Aug Tech" not in Path(jul_res["html_path"]).read_text(encoding="utf-8")

    # 2. Test full range from 1-Jul to today
    all_res = engine.generate(view_type="afa_table", start_date="1-Jul")
    assert all_res["applications_count"] == 3

    # 3. Test weekly reports from 1-Jul
    weekly_reports = engine.generate_weekly_reports(start_date="1-Jul", end_date="2026-07-15", view_type="afa_table")
    assert len(weekly_reports) >= 2
    for rep in weekly_reports:
        assert Path(rep["pdf_path"]).exists()


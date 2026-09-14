"""Tests for job archiving, content extraction, and dual-asset preservation."""

from pathlib import Path
from src.core.storage import JobAgentStorage
from src.tools.archive.extractor import JobContentExtractor
from src.tools.job_archive_tool import JobArchiveEngine


SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Senior Cloud Architect - FutureTech</title></head>
<body>
  <nav class="navbar"><a href="/">Home</a><a href="/jobs">Jobs</a></nav>
  <div class="cookie-consent-banner">Please accept all cookies</div>
  <script>console.log("tracking pixel");</script>
  
  <main class="job-description">
    <h1>Senior Cloud Architect</h1>
    <p class="company">FutureTech GmbH</p>
    <div class="meta">Location: Remote Germany | Salary: 85.000 - 105.000 EUR pro Jahr</div>
    
    <h2>About the Role</h2>
    <p>We are seeking an experienced architect to design AWS cloud systems.</p>
    
    <h2>Requirements</h2>
    <ul>
      <li>8+ years of software engineering</li>
      <li>Strong Python and AWS knowledge</li>
      <li>Kubernetes and Terraform experience</li>
    </ul>
  </main>
  
  <footer>Copyright 2026 FutureTech</footer>
</body>
</html>
"""


def test_content_extractor():
    extractor = JobContentExtractor()
    md = extractor.to_markdown(SAMPLE_HTML, title="Senior Cloud Architect", company="FutureTech GmbH")
    
    assert "# Senior Cloud Architect" in md
    assert "FutureTech GmbH" in md
    assert "cookie-consent-banner" not in md
    assert "tracking pixel" not in md
    assert "Requirements" in md

    meta = extractor.extract_metadata(SAMPLE_HTML)
    assert meta["work_model"] == "Remote"
    assert "85.000" in meta["salary"]


def test_job_archive_engine(tmp_path: Path):
    db_path = tmp_path / "test_archive.db"
    storage = JobAgentStorage(db_path=str(db_path))

    engine = JobArchiveEngine(storage=storage)
    engine.archive_dir = tmp_path / "archives"
    engine.archive_dir.mkdir(parents=True, exist_ok=True)
    engine.snapshotter.output_dir = tmp_path / "snapshots"
    engine.snapshotter.output_dir.mkdir(parents=True, exist_ok=True)

    res = engine.archive(
        company="FutureTech GmbH",
        role="Senior Cloud Architect",
        job_url="https://futuretech.example.com/jobs/123",
        raw_html=SAMPLE_HTML,
        qa_pairs={"Expected Salary?": "95,000 EUR", "Notice Period?": "1 month"},
    )

    assert res["application_id"] > 0
    # Markdown content is stored in the DB (not a file) — verify DB holds it.
    assert res["markdown_path"] == "stored_in_db"
    app_md = storage.get_application_by_company("FutureTech GmbH")
    assert app_md is not None and (app_md.get("job_description_md") or "")
    assert res["snapshot_pdf_path"] is not None
    assert Path(res["snapshot_pdf_path"]).exists()
    assert Path(res["snapshot_pdf_path"]).stat().st_size > 1000

    # Verify database entry
    app = storage.get_application_by_company("FutureTech GmbH")
    assert app is not None
    assert app["role"] == "Senior Cloud Architect"
    assert "85.000" in (app["salary_info"] or "")

    # Verify QA Memory saved
    ans = storage.get_qa_answer("Notice Period?")
    assert ans == "1 month"


def test_job_archive_ssrf_protection(tmp_path: Path):
    """Verify that private IP / loopback / metadata URLs are rejected by SSRF guard."""
    from src.tools.archive.url_guard import is_safe_url

    assert is_safe_url("http://127.0.0.1:8765/api/v1/auth/pair") is False
    assert is_safe_url("http://localhost:8080") is False
    assert is_safe_url("http://169.254.169.254/latest/meta-data") is False
    assert is_safe_url("http://10.0.0.1/admin") is False
    assert is_safe_url("http://192.168.1.1/secret") is False
    assert is_safe_url("file:///etc/passwd") is False

    storage = JobAgentStorage(db_path=str(tmp_path / "test_ssrf.db"))
    engine = JobArchiveEngine(storage=storage)
    engine.archive_dir = tmp_path / "archives"
    engine.archive_dir.mkdir(parents=True, exist_ok=True)

    # Calling archive with an SSRF URL should reject snapshot generation
    res = engine.archive(
        company="EvilCorp",
        role="Hacker",
        job_url="http://127.0.0.1:8765/api/v1/auth/pair",
    )
    assert res["snapshot_pdf_path"] is None


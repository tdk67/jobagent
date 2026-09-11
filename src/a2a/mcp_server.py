"""Model Context Protocol (MCP) server for JobAgent.

Exposes JobAgent capabilities as native tools for MCP-compatible personal agents
(e.g., Claude Desktop, Hermes, OpenClaw, Cursor, OpenBot).
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastmcp import FastMCP

from src.core.config import load_config
from src.core.storage import JobAgentStorage
from src.tools.email_ingest_tool import EmailIngestEngine
from src.tools.job_archive_tool import JobArchiveEngine
from src.tools.report_render_tool import ReportRenderEngine

# Initialize FastMCP Server
mcp = FastMCP(
    name="JobAgent",
    instructions=(
        "Autonomous Background Career CRM & Statutory Compliance Agent. "
        "Use this server to triage job applications, detect interviews, archive postings with PDF snapshots, "
        "and generate statutory proof reports (German Agentur für Arbeit)."
    ),
)

_engines: Dict[str, Any] = {}


def _get_engines() -> Dict[str, Any]:
    """Lazily initializes storage and tool engines upon first tool invocation."""
    if not _engines:
        cfg = load_config()
        storage = JobAgentStorage(cfg.storage.database_path)
        _engines["storage"] = storage
        _engines["email"] = EmailIngestEngine(storage=storage, config=cfg)
        _engines["archive"] = JobArchiveEngine(storage=storage, config=cfg)
        _engines["report"] = ReportRenderEngine(storage=storage, config=cfg)
    return _engines


@mcp.tool()
def jobagent_triage_inbox(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Scans and triages incoming emails from connected inboxes (Desktop Outlook, Gmail, IMAP).
    
    Supports date range filtering (e.g. start_date='2026-07-01' or '1-Jul', end_date='2026-07-07').
    Classifies messages into applications, rejections, or interviews, and updates the local CRM database.
    """
    engines = _get_engines()
    results = engines["email"].run_triage(limit=limit, start_date=start_date, end_date=end_date)
    return json.dumps(results, indent=2)


@mcp.tool()
def jobagent_archive_posting(
    company: str,
    role: str,
    job_url: str = "",
    raw_html: str = "",
) -> str:
    """Preserves a job posting as clean Markdown text and full-page visual PDF snapshot before the listing expires."""
    engines = _get_engines()
    result = engines["archive"].archive(
        company=company,
        role=role,
        job_url=job_url if job_url else None,
        raw_html=raw_html if raw_html else None,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
def jobagent_get_interviews() -> str:
    """Retrieves all scheduled, pending, and past job interviews with meeting links and status."""
    engines = _get_engines()
    interviews = engines["storage"].list_interviews()
    return json.dumps(interviews, indent=2)


@mcp.tool()
def jobagent_generate_compliance_report(report_type: str = "dashboard") -> str:
    """Generates visual HTML dashboards and compliance PDFs.

    Parameters:
        report_type: 'dashboard' (candidate KPI view), 'afa_table' (official German Agentur für Arbeit Eigenbemühungsnachweis), or 'agency_summary'.
    """
    engines = _get_engines()
    result = engines["report"].generate(view_type=report_type, export_pdf=True)
    return json.dumps(result, indent=2)


@mcp.tool()
def jobagent_query_qa_memory(question: str) -> str:
    """Queries candidate's verified screening question memory (salary expectations, notice period, work authorization)."""
    engines = _get_engines()
    ans = engines["storage"].get_qa_answer(question)
    return json.dumps({"question": question, "answer": ans}, indent=2)


if __name__ == "__main__":
    mcp.run()

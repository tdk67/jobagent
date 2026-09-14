"""Model Context Protocol (MCP) server for JobAgent.

Exposes JobAgent capabilities as native tools for MCP-compatible personal agents
(e.g., Claude Desktop, Hermes, OpenClaw, Cursor, OpenBot).
Pure protocol adapter delegating all business logic to the shared Service Layer.
"""

from __future__ import annotations

import json
from typing import Optional

from fastmcp import FastMCP

from src.services.container import get_service_container

# Initialize FastMCP Server
mcp = FastMCP(
    name="JobAgent",
    instructions=(
        "Autonomous Background Career CRM & Statutory Compliance Agent. "
        "Use this server to triage job applications, detect interviews, archive postings with PDF snapshots, "
        "and generate statutory proof reports (German Agentur für Arbeit)."
    ),
)


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
    services = get_service_container()
    results = services.emails.triage_inbox(limit=limit, start_date=start_date, end_date=end_date)
    return json.dumps(results, indent=2)


@mcp.tool()
def jobagent_archive_posting(
    company: str,
    role: str,
    job_url: str = "",
    raw_html: str = "",
) -> str:
    """Preserves a job posting as clean Markdown text and full-page visual PDF snapshot before the listing expires."""
    services = get_service_container()
    result = services.archives.archive(
        company=company,
        role=role,
        job_url=job_url if job_url else None,
        raw_html=raw_html if raw_html else None,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
def jobagent_get_interviews() -> str:
    """Retrieves all scheduled, pending, and past job interviews with meeting links and status."""
    services = get_service_container()
    interviews = services.applications.list_interviews()
    return json.dumps(interviews, indent=2)


@mcp.tool()
def jobagent_generate_compliance_report(report_type: str = "dashboard") -> str:
    """Generates visual HTML dashboards and compliance PDFs.

    Parameters:
        report_type: 'dashboard' (candidate KPI view), 'afa_table' (official German Agentur für Arbeit Eigenbemühungsnachweis), or 'agency_summary'.
    """
    services = get_service_container()
    result = services.reports.generate(view_type=report_type, export_pdf=True)
    return json.dumps(result, indent=2)


@mcp.tool()
def jobagent_query_qa_memory(question: str) -> str:
    """Queries candidate's verified screening question memory (salary expectations, notice period, work authorization)."""
    services = get_service_container()
    ans = services.applications.get_qa_answer(question)
    return json.dumps({"question": question, "answer": ans}, indent=2)


if __name__ == "__main__":
    mcp.run(show_banner=False)

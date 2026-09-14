"""JobAgent: Main CLI and Entry Point.

Usage:
  python run_agent.py --demo         # Runs complete end-to-end hackathon demo
  python run_agent.py --cycle        # Runs single background triage & compliance cycle
  python run_agent.py --server       # Starts A2A REST/SSE Gateway (port 8765)
  python run_agent.py --mcp          # Starts Model Context Protocol (MCP) Server
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

# Force UTF-8 on Windows terminals
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

from src.agent.coordinator import JobAgentCoordinator
from src.core.config import load_config
from src.core.storage import JobAgentStorage
from src.tools.email.adapters import MockEmailAdapter


def run_demo(demo_db_path: str = "data/jobagent_demo.db"):
    """Runs a complete end-to-end demonstration for hackathon judges in an isolated database."""
    print("=" * 70)
    print(">> JobAgent: Demonstration Simulation Mode")
    print(f"   (Using isolated demo database: {demo_db_path})")
    print("=" * 70)

    cfg = load_config()
    cfg.storage.database_path = demo_db_path

    # Clean previous demo DB run if exists
    demo_p = Path(demo_db_path)
    if demo_p.exists():
        try:
            demo_p.unlink()
        except Exception:
            pass

    db = JobAgentStorage(demo_db_path)

    print("\n[Step 1/4] Seeding Candidate Applications & Profile...")
    db.upsert_application(
        company="Chrono24",
        role="Senior Java Developer",
        applied_date="2026-09-02T10:00:00Z",
        status="Applied",
        location="Karlsruhe / Remote",
        job_url="https://chrono24.jobs.personio.de/job/2729224/apply",
    )
    db.upsert_application(
        company="Finanz Informatik",
        role="Software Engineer Backend",
        applied_date="2026-09-03T11:00:00Z",
        status="Applied",
        location="Frankfurt am Main",
    )
    print("  ✓ Applications logged in isolated demo SQLite CRM")

    print("\n[Step 2/4] Archiving Job Posting (Dual-Asset: Markdown + PDF Snapshot)...")
    coordinator = JobAgentCoordinator(config=cfg, storage=db)
    archive_result = coordinator.archive_engine.archive(
        company="Chrono24",
        role="Senior Java Developer",
        job_url="https://chrono24.jobs.personio.de/job/2729224/apply",
        raw_html="<html><body><h1>(Senior) Java Developer (m/f/d)</h1><p>Chrono24 GmbH - Remote</p><p>Salary: 75.000 - 95.000 EUR</p><ul><li>Java, Spring Boot, PostgreSQL</li></ul></body></html>",
    )
    print(f"  ✓ Clean Markdown: {archive_result['markdown_path']}")
    if archive_result.get("snapshot_pdf_path"):
        print(f"  ✓ High-Res Visual PDF: {archive_result['snapshot_pdf_path']}")

    print("\n[Step 3/4] Ingesting Inbox Emails & Detecting Genuine Interviews...")
    # Inject synthetic inbox with genuine interview, rejection, and deceptive sales pitch
    mock_emails = [
        {
            "entry_id": "demo_email_001",
            "sender_name": "Chrono24 Talent Acquisition",
            "sender_email": "recruiting@chrono24.com",
            "subject": "Einladung zum Vorstellungsgespräch: Senior Java Developer",
            "body": "Lieber Bewerber, gerne möchten wir Sie zu einem ersten Videointerview via Microsoft Teams einladen. Link: https://teams.microsoft.com/l/meetup-join/demo-chrono24",
            "received_time": "2026-09-09T14:30:00Z",
        },
        {
            "entry_id": "demo_email_002",
            "sender_name": "Finanz Informatik HR",
            "sender_email": "recruiting@f-i.de",
            "subject": "Ihre Bewerbung bei Finanz Informatik",
            "body": "Sehr geehrter Bewerber, leider müssen wir Ihnen mitteilen, dass wir uns für andere Kandidaten entschieden haben.",
            "received_time": "2026-09-08T16:00:00Z",
        },
        {
            "entry_id": "demo_email_003",
            "sender_name": "Sales Webinar",
            "sender_email": "promo@salescoach.com",
            "subject": "Exklusives Webinar für Vertrieb und Finanzkonzepte!",
            "body": "Nutzen Sie unseren Bildungsgutschein für das ultimative Coaching.",
            "received_time": "2026-09-10T08:00:00Z",
        },
    ]

    coordinator.email_engine.adapters = [MockEmailAdapter(mock_emails)]
    cycle_res = coordinator.run_autonomous_cycle(email_limit=10)

    print(f"  ✓ Emails Scanned: {cycle_res['triage_summary']['total_scanned']}")
    print(f"  ✓ Interviews Detected: {cycle_res['triage_summary']['interviews_found']}")
    print(f"  ✓ Rejections Processed: {cycle_res['triage_summary']['rejections_found']}")
    print(f"  ✓ Sales Spam Discarded: {cycle_res['triage_summary']['noise_filtered']}")

    print("\n[Step 4/4] Generating Multi-Stakeholder Compliance & Proof Reports...")
    for report_name, pdf_path in cycle_res["reports_generated"].items():
        print(f"  ✓ Generated {report_name.upper()}: {pdf_path}")

    print("\n" + "=" * 70)
    print("🏆 SUMMARY: JobAgent ran autonomously in the background.")
    if cycle_res.get("agent_briefing"):
        print(f"🤖 LLM AGENT BRIEFING: {cycle_res['agent_briefing']}")
    if cycle_res["requires_human_decision"]:
        print("🔔 HUMAN ATTENTION REQUIRED:")
        for alert in cycle_res["actionable_alerts"]:
            print(f"   👉 Interview Invitation: {alert['company']} ({alert['subject']})")
            print(f"      Meeting Link: {alert.get('meeting_link', 'Pending')}")
    else:
        print("😴 No human interruption needed. Quiet background operation maintained.")
    print("=" * 70)


# =============================================================================
# CLI Command Handlers (SRP Modularization)
# =============================================================================

def cmd_import_summary(args: argparse.Namespace, cfg: Any, parser: argparse.ArgumentParser) -> None:
    if args.import_summary is None:
        parser.error("--import-summary requires a path")
    storage = JobAgentStorage(cfg.storage.database_path)
    print("=" * 70)
    print(f">> JobAgent: Importing Applications from Summary (DB: {cfg.storage.database_path})")
    print("=" * 70)
    sum_file = args.import_summary
    res = storage.import_from_summary(sum_file)
    print(f"✓ Successfully imported {res['applications_imported']} applications")
    print(f"✓ Successfully imported {res['interviews_imported']} interviews")
    print("=" * 70)


def cmd_report(args: argparse.Namespace, cfg: Any) -> None:
    from src.tools.report_render_tool import ReportRenderEngine
    storage = JobAgentStorage(cfg.storage.database_path)
    # NOTE: import_from_summary is NOT invoked here. Historical data must be
    # imported explicitly via --import-summary; auto-importing from a hidden
    # hardcoded path was removed (F5 data-integrity fix).
    engine = ReportRenderEngine(config=cfg, storage=storage)
    view = args.report

    print("=" * 70)
    print(">> JobAgent: Generating Reports")
    print("=" * 70)

    if args.weekly:
        start_d = args.start_date or "2026-07-01"
        print(f"Generating week-by-week {view} reports starting from {start_d}...")
        reports = engine.generate_weekly_reports(
            start_date=start_d,
            end_date=args.end_date,
            view_type=view if view != "all" else "afa_table",
        )
        print(f"\n✓ Generated {len(reports)} weekly reports:")
        for r in reports:
            print(f"  • {r.get('report_period')}: {r.get('pdf_path')} ({r.get('total_applications')} applications)")
    elif view == "all":
        print("Generating all default reports...")
        reports = engine.generate_all_views(start_date=args.start_date, end_date=args.end_date)
        for k, v in reports.items():
            print(f"  ✓ {k.upper()}: {v.get('pdf_path')}")
    else:
        filename = None
        if args.start_date:
            s_clean = args.start_date.replace(".", "").replace("-", "")
            e_clean = (args.end_date or "today").replace(".", "").replace("-", "")
            filename = f"{view}_{s_clean}_to_{e_clean}.pdf"
        r = engine.generate(
            view_type=view,
            export_pdf=True,
            start_date=args.start_date,
            end_date=args.end_date,
            output_pdf_name=filename,
        )
        print(f"✓ Generated {view} report:")
        print(f"  • Period: {r.get('report_period')}")
        print(f"  • HTML: {r.get('html_path')}")
        print(f"  • PDF: {r.get('pdf_path')}")
        print(f"  • Total Applications: {r.get('total_applications')}")
    print("=" * 70)


def cmd_triage(args: argparse.Namespace, cfg: Any) -> None:
    from src.tools.email_ingest_tool import EmailIngestEngine
    storage = JobAgentStorage(cfg.storage.database_path)
    engine = EmailIngestEngine(config=cfg, storage=storage)

    print("=" * 70)
    print(f">> JobAgent: Scanning Connected Email Inboxes (DB: {cfg.storage.database_path})")
    print("=" * 70)

    if args.weekly:
        start_d = args.start_date or "2026-07-01"
        from datetime import datetime, timedelta, timezone
        from src.utils.date_utils import parse_flexible_date
        s_str = parse_flexible_date(start_d) or "2026-07-01"
        e_str = parse_flexible_date(args.end_date) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cur_start = datetime.strptime(s_str, "%Y-%m-%d").date()
        target_end = datetime.strptime(e_str, "%Y-%m-%d").date()

        print(f"Ingesting emails week-by-week from {s_str} to {e_str}...")
        while cur_start <= target_end:
            days_to_sun = 6 - cur_start.weekday()
            cur_end = min(cur_start + timedelta(days=days_to_sun), target_end)
            w_start = cur_start.strftime("%Y-%m-%d")
            w_end = cur_end.strftime("%Y-%m-%d")
            kw = cur_start.isocalendar()[1]

            res = engine.run_triage(start_date=w_start, end_date=w_end)
            print(f"  • KW {kw} ({w_start} – {w_end}): Scanned {res.get('total_scanned', 0)} | Confirmations: {res.get('confirmations_found', 0)} | Interviews: {res.get('interviews_found', 0)} | Rejections: {res.get('rejections_found', 0)}")
            cur_start = cur_end + timedelta(days=1)
    else:
        res = engine.run_triage(start_date=args.start_date, end_date=args.end_date)
        period_desc = f" ({args.start_date or 'beginning'} to {args.end_date or 'today'})" if (args.start_date or args.end_date) else ""
        print(f"✓ Scanned: {res.get('total_scanned', 0)} messages{period_desc}")
        print(f"  • Confirmations: {res.get('confirmations_found', 0)}")
        print(f"  • Interviews: {res.get('interviews_found', 0)}")
        print(f"  • Rejections: {res.get('rejections_found', 0)}")
        print(f"  • Noise Filtered: {res.get('noise_filtered', 0)}")
        if res.get("actionable_alerts"):
            print("\n🔔 Actionable Alerts:")
            for a in res["actionable_alerts"]:
                print(f"   👉 {a.get('type')}: {a.get('company')} ({a.get('subject')})")
                print(f"      Meeting: {a.get('meeting_link')}")
    print("=" * 70)


def cmd_fetch_emails(args: argparse.Namespace, cfg: Any) -> None:
    from src.tools.email_ingest_tool import EmailIngestEngine
    storage = JobAgentStorage(cfg.storage.database_path)
    engine = EmailIngestEngine(config=cfg, storage=storage)
    print("=" * 70)
    print(f">> JobAgent: Downloading & Caching Raw Emails (DB: {cfg.storage.database_path})")
    print("=" * 70)
    fetched = engine.fetch_and_cache_emails(start_date=args.start_date, end_date=args.end_date)
    print(f"✓ Downloaded and cached {len(fetched)} raw emails into raw_emails table.")
    print("=" * 70)


def cmd_cluster(args: argparse.Namespace, cfg: Any) -> None:
    from src.tools.email_ingest_tool import EmailIngestEngine
    storage = JobAgentStorage(cfg.storage.database_path)
    engine = EmailIngestEngine(config=cfg, storage=storage)
    print("=" * 70)
    print(f">> JobAgent: Clustering & Deduplicating Cached Emails (DB: {cfg.storage.database_path})")
    print("=" * 70)
    res = engine.cluster_cached_emails(start_date=args.start_date, end_date=args.end_date)
    print(f"✓ Processed: {res.get('total_cached_processed', 0)} cached emails")
    print(f"  • Confirmations: {res.get('confirmations_found', 0)}")
    print(f"  • Interviews: {res.get('interviews_found', 0)}")
    print(f"  • Rejections: {res.get('rejections_found', 0)}")
    print(f"  • Noise Filtered: {res.get('noise_filtered', 0)}")
    print("=" * 70)


def cmd_cycle(cfg: Any) -> None:
    coordinator = JobAgentCoordinator(config=cfg)
    res = coordinator.run_autonomous_cycle()
    print(json.dumps(res, indent=2))


def cmd_agent(cfg: Any, poll_seconds: Optional[int] = None) -> None:
    """Runs the Strands event-loop autonomous agent (wake-perceive-decide-execute-record)."""
    from src.agent.event_loop import EventLoopAgent

    poll = poll_seconds or getattr(cfg.agent, "poll_seconds", 300) or 300
    print("=" * 70)
    print(f">> JobAgent Event-Loop Agent (Poll: {poll}s, DB: {cfg.storage.database_path})")
    print(">> LLM available:", bool(os.getenv("GEMINI_API_KEY") or os.getenv("AWS_ACCESS_KEY_ID")))
    print(">> Press Ctrl+C to stop agent.")
    print("=" * 70)
    loop = EventLoopAgent(coordinator=JobAgentCoordinator(config=cfg), poll_seconds=poll)
    try:
        loop.run()
    except KeyboardInterrupt:
        print("\n>> Agent stopped cleanly.")


def cmd_daemon(cfg: Any, interval_minutes: int = 30) -> None:
    """Runs autonomous triage & compliance cycles periodically in the background (P3)."""
    import time
    from datetime import datetime
    coordinator = JobAgentCoordinator(config=cfg)
    interval_seconds = max(60, interval_minutes * 60)
    print("=" * 70)
    print(f">> JobAgent Autonomous Daemon Started (Interval: {interval_minutes}m, DB: {cfg.storage.database_path})")
    print(">> Press Ctrl+C to stop daemon.")
    print("=" * 70)
    cycle_count = 1
    try:
        while True:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[Cycle #{cycle_count} @ {now_str}] Running autonomous cycle...")
            try:
                res = coordinator.run_autonomous_cycle()
                log.debug("Autonomous cycle completed: %s", res)
                apps_cnt = res.get("applications_found", 0) if isinstance(res, dict) else 0
                alerts_cnt = len(res.get("actionable_alerts", [])) if isinstance(res, dict) else 0
                print(f"✓ Cycle completed cleanly ({apps_cnt} applications checked, {alerts_cnt} alerts).")
            except Exception as err:
                print(f"⚠ Autonomous cycle encountered an error: {err}")
            cycle_count += 1
            print(f"Sleeping for {interval_minutes} minutes...")
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("\n>> Autonomous Daemon stopped cleanly.")


def cmd_cover_letter(args: argparse.Namespace) -> None:
    from src.tools.cover_letter_tool import CoverLetterEngine
    role_for_letter = args.role or "Software Engineer"
    engine = CoverLetterEngine()
    print("=" * 70)
    print(f">> JobAgent: Generating DIN 5008 Cover Letter ({args.lang.upper()})")
    print("=" * 70)
    res = engine.generate(company=args.company, role=role_for_letter, lang=args.lang)
    print(f"✓ Target Company: {res['company']}")
    print(f"✓ Target Role:    {res['role']}")
    print(f"✓ Language:       {res['language']}")
    print(f"✓ HTML Template:  {res['html_path']}")
    print(f"✓ PDF Document:   {res['pdf_path']}")
    print("=" * 70)


def cmd_server(args: argparse.Namespace, cfg: Any) -> None:
    import uvicorn
    from src.a2a.server import create_a2a_app
    # Override order: CLI flag > env (A2A_HOST/A2A_PORT) > config value.
    host = args.host or os.getenv("A2A_HOST") or cfg.a2a.host
    port_env = os.getenv("A2A_PORT")
    port = args.port or (int(port_env) if port_env else cfg.a2a.port)
    # Keep the gateway's Host-header guard in sync with the effective bind:
    # the configured host must be one of the Hosts the middleware accepts.
    cfg.a2a.host = host
    cfg.a2a.port = port
    app = create_a2a_app(config=cfg)
    print(f"Starting JobAgent A2A Gateway on http://{host}:{port}...")
    uvicorn.run(app, host=host, port=port)


def cmd_mcp() -> None:
    from src.a2a.mcp_server import mcp
    print("Starting JobAgent FastMCP server...")
    mcp.run()

def cmd_sync_to_vps(url: str, token: str) -> None:
    from src.a2a.sync_client import JobAgentSyncClient
    client = JobAgentSyncClient(target_url=url, token=token)
    client.push_to_vps()

def main():
    parser = argparse.ArgumentParser(description="JobAgent CLI")
    parser.add_argument("--demo", action="store_true", help="Run hackathon demonstration simulation")
    parser.add_argument("--cycle", action="store_true", help="Run autonomous background triage and reporting cycle")
    parser.add_argument("--daemon", action="store_true", help="Run autonomously in a continuous background loop")
    parser.add_argument("--schedule", type=int, default=None, metavar="MINUTES", help="Interval in minutes for autonomous background daemon")
    parser.add_argument("--server", action="store_true", help="Start A2A REST/SSE server for browser extension and external agents")
    parser.add_argument("--mcp", action="store_true", help="Start FastMCP server for Claude Desktop / Cursor / Hermes")
    parser.add_argument("--port", type=int, default=None, help="Port for A2A server (defaults to config.json)")
    parser.add_argument("--host", type=str, default=None, help="Host for A2A server (defaults to config.json)")
    parser.add_argument("--db", type=str, default=None, help="Path to custom SQLite database file (default: data/jobagent.db)")
    parser.add_argument("--reset-db", action="store_true", help="Delete and re-initialize target SQLite database to empty state")
    parser.add_argument("--report", choices=["all", "afa_table", "dashboard", "agency_summary"], default=None, help="Generate compliance proof tables or KPI dashboards")
    parser.add_argument("--start-date", type=str, default=None, help="Start date for reports (e.g. '2026-07-01' or '1-Jul')")
    parser.add_argument("--end-date", type=str, default=None, help="End date for reports (defaults to today)")
    parser.add_argument("--weekly", action="store_true", help="Generate separate reports week-by-week between start date and end date")
    parser.add_argument("--fetch-emails", action="store_true", help="Download and cache raw emails week-by-week into SQLite raw_emails table")
    parser.add_argument("--cluster", action="store_true", help="Run offline deduplication and application clustering on cached emails")
    parser.add_argument("--triage", action="store_true", help="Scan connected email inboxes and update local CRM")
    parser.add_argument(
        "--import-summary",
        type=str,
        nargs="?",
        const=None,
        default=argparse.SUPPRESS,
        help="Import historical applications and interviews from applications_summary.json (a summary path is required)",
    )
    parser.add_argument("--cover-letter", action="store_true", help="Generate a DIN 5008 German/English cover letter")
    parser.add_argument("--company", type=str, default="Unternehmen", help="Target company name for cover letter")
    parser.add_argument("--role", type=str, default=None, help="Target job title/role for cover letter")
    parser.add_argument("--lang", type=str, default="de", choices=["de", "en"], help="Language for cover letter (de or en)")
    parser.add_argument("--sync-to-vps", type=str, default=None, help="Securely sync local personal data to a remote VPS JobAgent instance (requires HTTPS URL)")
    parser.add_argument("--token", type=str, default=None, help="API Token for VPS Sync authentication")
    parser.add_argument(
        "--agent",
        action="store_true",
        help="Run the Strands event-loop autonomous agent (wake-perceive-decide-execute-record).",
    )
    parser.add_argument(
        "--agent-interval",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Agent loop poll interval in seconds (default: config or 300s).",
    )
    args = parser.parse_args()

    cfg = load_config()
    if args.db:
        cfg.storage.database_path = args.db

    if args.reset_db:
        db_p = Path(cfg.storage.database_path)
        if db_p.exists():
            try:
                db_p.unlink()
                print(f"✓ Target database '{cfg.storage.database_path}' has been reset to an empty state.")
            except Exception as e:
                print(f"⚠ Warning: Could not delete database file: {e}")
        JobAgentStorage(cfg.storage.database_path)

    if args.demo:
        run_demo()
    elif hasattr(args, "import_summary"):
        cmd_import_summary(args, cfg, parser)
    elif args.report:
        cmd_report(args, cfg)
    elif args.fetch_emails:
        cmd_fetch_emails(args, cfg)
    elif args.cluster:
        cmd_cluster(args, cfg)
    elif args.triage:
        cmd_triage(args, cfg)
    elif args.daemon or args.schedule:
        interval = args.schedule or 30
        cmd_daemon(cfg, interval_minutes=interval)
    elif args.agent:
        cmd_agent(cfg, poll_seconds=args.agent_interval)
    elif args.cycle:
        cmd_cycle(cfg)
    elif args.cover_letter:
        cmd_cover_letter(args)
    elif args.server:
        cmd_server(args, cfg)
    elif args.mcp:
        cmd_mcp()
    elif args.sync_to_vps:
        if not args.token:
            print("[-] Error: --token is required for secure VPS sync.")
            return
        cmd_sync_to_vps(args.sync_to_vps, args.token)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

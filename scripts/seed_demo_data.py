#!/usr/bin/env python3
"""JobAgent — demo data seeder.

Builds a rich, realistic synthetic career dataset in an isolated demo DB
so the Playwright showcase / video pitch can be recorded without touching
real data. All personas are fictional (Jane Doe / example.com).

Usage:
    venv/bin/python scripts/seed_demo_data.py [--db data/jobagent_demo.db] [--reset]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.storage import JobAgentStorage
from src.core.profile import load_profile  # noqa: F401


def iso(days_ago: int, hour: int = 10, minute: int = 0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()


def seed(db_path: str, reset: bool) -> None:
    if reset and Path(db_path).exists():
        Path(db_path).unlink()
    db = JobAgentStorage(db_path)

    # ── Applications: a realistic multi-cycle arc ─────────────────────
    apps = [
        # (company, role, applied_days_ago, status, source, location, salary, job_url)
        ("Chrono24", "Senior Java Developer", 12, "Interview", "Job Portal (Personio)",
         "Karlsruhe / Remote", "75.000 - 95.000 EUR",
         "https://chrono24.jobs.personio.de/job/2729224/apply"),
        ("Finanz Informatik", "Backend Software Engineer", 11, "Rejected", "Direct (Career Site)",
         "Frankfurt am Main", "70.000 - 88.000 EUR", ""),
        ("Jobgether", "Platform Engineer (m/f/d)", 9, "Applied", "Job Portal (Jobgether)",
         "Remote (EU)", "65.000 - 85.000 EUR",
         "https://jobgether.com/offer/platform-engineer-2026"),
        ("Michael Page", "Senior DevOps Engineer", 8, "Applied", "Recruitment Agency",
         "Munich", "80.000 - 100.000 EUR",
         "https://michaelpage.de/jobs/senior-devops-engineer"),
        ("Devoteam", "Cloud Solutions Architect", 7, "Applied", "Recruitment Agency",
         "Remote / Berlin", "85.000 - 110.000 EUR",
         "https://devoteam.com/careers/cloud-architect"),
        ("SAP SE", "Backend Developer (Java)", 20, "Rejected", "Direct (Career Site)",
         "Walldorf / Remote", "72.000 - 92.000 EUR", ""),
        ("SAP SE", "Backend Developer (Java) - Reapply", 4, "Applied", "Direct (Career Site)",
         "Walldorf / Remote", "72.000 - 92.000 EUR",
         "https://jobs.sap.com/job/backend-java-2026"),
        ("GarageBand GmbH", "Senior Software Engineer", 15, "Interview", "Referral",
         "Berlin", "88.000 - 105.000 EUR",
         "https://garageband.example.com/jobs/senior-engineer"),
        ("Zalando SE", "Software Engineer (Kotlin)", 5, "Applied", "Job Portal (LinkedIn)",
         "Berlin / Remote", "70.000 - 90.000 EUR", ""),
        ("Deutsche Bank", "Java Lead Developer", 2, "Applied", "Direct (Career Site)",
         "Frankfurt am Main", "95.000 - 120.000 EUR",
         "https://db.jobs/java-lead-developer"),
    ]
    for c, r, ago, st, src, loc, sal, url in apps:
        db.upsert_application(
            company=c, role=r, applied_date=iso(ago, 9), status=st,
            source=src, location=loc, salary_info=sal, job_url=url or None,
        )

    # ── Interviews ────────────────────────────────────────────────────
    # Chrono24 upcoming interview (the star of the demo)
    db.record_interview(
        company="Chrono24",
        role="Senior Java Developer",
        interview_date=iso(0, 14, 30),
        interview_type="Interview Invitation",
        meeting_link="https://teams.microsoft.com/l/meetup-join/demo-chrono24-interview",
        status="Pending_Confirmation",
        notes="Detected from email: Einladung zum Vorstellungsgespräch",
    )
    # GarageBand past interview (moved to rejection → preserves Had Interview badge)
    db.record_interview(
        company="GarageBand GmbH",
        role="Senior Software Engineer",
        interview_date=iso(6, 13, 0),
        interview_type="Technical Interview",
        meeting_link="",
        status="Completed",
        notes="Technical round, went well",
    )

    # ── Email interactions (triage history) ───────────────────────────
    emails = [
        # (company, sender, subject, category, days_ago, confidence)
        ("Chrono24", "recruiting@chrono24.com",
         "Einladung zum Vorstellungsgespräch: Senior Java Developer",
         "interview_invitation", 0, 0.99),
        ("Chrono24", "recruiting@chrono24.com",
         "Re: Ihre Bewerbung – Terminabstimmung",
         "interview_follow_up", 1, 0.97),
        ("Finanz Informatik", "hr@f-i.de",
         "Ihre Bewerbung bei Finanz Informatik",
         "rejection", 6, 0.95),
        ("GarageBand GmbH", "jobs@garageband.example.com",
         "Thank you for applying — but we've moved on",
         "rejection", 5, 0.91),
        ("SAP SE", "careers@sap.com",
         "Application status update SAP SE",
         "rejection", 12, 0.9),
        ("Sales Webinar", "promo@salescoach.example.com",
         "Exklusives Webinar für Vertrieb und Finanzkonzepte!",
         "noise", 3, 0.88),
        ("LinkedIn Job Alerts", "jobs-list@linkedin.com",
         "Your weekly job digest — 24 new roles",
         "noise", 2, 0.84),
        ("Jobgether", "team@jobgether.com",
         "Your application has been received",
         "confirmation", 9, 0.9),
        ("Michael Page", "consultant@michaelpage.de",
         "We received your CV — next steps",
         "confirmation", 8, 0.92),
        ("Devoteam", "careers@devoteam.com",
         "Application confirmation Devoteam",
         "confirmation", 7, 0.91),
    ]
    for company, sender, subject, cat, ago, conf in emails:
        app = db.get_application_by_company(company)
        app_id = app["id"] if app else None
        db.record_email_interaction(
            entry_id=f"demo_{company.lower().replace(' ', '_')}_{ago}",
            category=cat,
            sender_name=company or sender.split("@")[0],
            sender_email=sender,
            subject=subject,
            received_time=iso(ago, 9 + (ago % 3)),
            preview=subject[:120],
            application_id=app_id,
            confidence_score=conf,
        )

    # ── Q&A memory (screening answers) ────────────────────────────────
    qa_pairs = [
        ("What are your salary expectations?",
         "Based on my experience and market data, I'm targeting a base salary between 80,000 and 95,000 EUR, flexible for equity or travel.",
         "profile"),
        ("What is your notice period?",
         "My current notice period is 3 months to the end of the quarter, negotiable depending on the role.",
         "profile"),
        ("Do you have a valid work permit for Germany?",
         "Yes, I hold an EU Blue Card and have full work authorization in Germany.",
         "profile"),
        ("What's your tech stack?",
         "Java, Spring Boot, Kotlin, PostgreSQL, Kafka, Docker, Kubernetes, AWS.",
         "profile"),
        ("Are you available for on-site work in Frankfurt?",
         "Yes, I am based in Frankfurt am Main and can be on-site as required, with hybrid preference.",
         "profile"),
    ]
    for q, a, cat in qa_pairs:
        db.save_qa_answer(question_text=q, answer=a, category=cat, verified=1, provenance="demo-seed")

    # ── Verify the seeded dataset ─────────────────────────────────────
    st = db.get_statistics()
    iv = db.list_interviews()
    print(f"✅ Seeded demo DB: {db_path}")
    print(f"   Applications: {st.get('total_applications')}")
    print(f"   Interviews:   {len(iv)} (Chrono24 pending, GarageBand completed)")
    print(f"   Q&A memory:   {len(qa_pairs)} entries")
    print(f"   Email interactions: {len(emails)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/jobagent_demo.db")
    ap.add_argument("--reset", action="store_true", help="Delete existing demo DB first")
    args = ap.parse_args()
    seed(args.db, args.reset)
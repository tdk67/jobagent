"""Unit tests for JobAgentCoordinator and Strands Agent autonomous pattern."""

import json
from pathlib import Path
import pytest

from src.agent.coordinator import JobAgentCoordinator
from src.core.config import AppConfig, AgentConfig, StorageConfig, ReportingConfig
from src.core.profile import CandidateProfile, PersonalInfo
from src.core.storage import JobAgentStorage
from src.tools.email.adapters import MockEmailAdapter


@pytest.fixture
def test_coordinator(tmp_path: Path) -> JobAgentCoordinator:
    db_path = tmp_path / "test_coordinator.db"
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    config = AppConfig(
        agent=AgentConfig(provider="gemini", model="gemini-3.8-flash", temperature=0.1),
        storage=StorageConfig(database_path=str(db_path)),
        reporting=ReportingConfig(output_dir=str(out_dir), enable_pdf_export=False),
    )
    storage = JobAgentStorage(str(db_path))
    profile = CandidateProfile(
        personal=PersonalInfo(fullName="Test Candidate", email="candidate@test.com")
    )
    return JobAgentCoordinator(config=config, storage=storage, profile=profile)


def test_coordinator_agent_initialization(test_coordinator: JobAgentCoordinator):
    """Verifies that the Strands Agent is instantiated with registered tools."""
    assert test_coordinator.agent is not None
    assert test_coordinator.agent.name == "JobAgent"
    assert len(test_coordinator.tools) >= 3
    assert "ingest_emails" in test_coordinator.agent.tool_names
    assert "generate_compliance_report" in test_coordinator.agent.tool_names


def test_coordinator_tools_session_binding(test_coordinator: JobAgentCoordinator):
    """Verifies that the agent tools properly mutate and access coordinator session state."""
    test_emails = [
        {
            "entry_id": "test_1",
            "sender_name": "Tech Corp HR",
            "sender_email": "hr@techcorp.com",
            "subject": "Interview Invitation: Backend Developer",
            "body": "We would like to invite you for an interview. Link: https://teams.microsoft.com/meet/123",
            "received_time": "2026-09-08T10:00:00Z",
        }
    ]
    test_coordinator.storage.upsert_application("Tech Corp", "Backend Developer")
    test_coordinator.email_engine.adapters = [MockEmailAdapter(test_emails)]

    # Find the ingest_emails tool from coordinator tools
    ingest_tool = None
    for t in test_coordinator.tools:
        name = getattr(t, "tool_name", "") or getattr(t, "__name__", "")
        if "ingest_emails" in name:
            ingest_tool = t
            break

    assert ingest_tool is not None, "ingest_emails tool not found on coordinator"
    res_str = ingest_tool(limit=10)
    res = json.loads(res_str)

    # Verify coordinator captured state from tool execution
    assert res["total_scanned"] == 1
    assert res["interviews_found"] == 1
    assert test_coordinator.latest_triage["total_scanned"] == 1


def test_coordinator_deterministic_cycle_fallback(test_coordinator: JobAgentCoordinator):
    """Verifies that run_autonomous_cycle completes reliably even without active cloud LLM."""
    test_coordinator.llm_available = False

    test_emails = [
        {
            "entry_id": "test_2",
            "sender_name": "Startup Inc",
            "sender_email": "jobs@startup.io",
            "subject": "Ihre Bewerbung bei Startup Inc",
            "body": "Leider müssen wir Ihnen mitteilen, dass wir uns für andere Bewerber entschieden haben.",
            "received_time": "2026-09-08T11:00:00Z",
        }
    ]
    test_coordinator.storage.upsert_application("Startup Inc", "Backend Developer")
    test_coordinator.email_engine.adapters = [MockEmailAdapter(test_emails)]

    cycle_res = test_coordinator.run_autonomous_cycle(email_limit=5)
    assert cycle_res["triage_summary"]["total_scanned"] == 1
    assert cycle_res["triage_summary"]["rejections_found"] == 1
    assert cycle_res["requires_human_decision"] is False
    assert cycle_res["agent_briefing"] is not None


def test_coordinator_multi_cycle_idempotency(test_coordinator: JobAgentCoordinator):
    """Verifies that running multiple background cycles does not create duplicate entries (H1)."""
    test_coordinator.llm_available = False

    test_emails = [
        {
            "entry_id": "stable_interview_msg_001",
            "sender_name": "Chrono24",
            "sender_email": "recruiting@chrono24.com",
            "subject": "Interview: Senior Java Developer",
            "body": "Termin am 25.09.2026 um 10:00 Uhr via Teams: https://teams.microsoft.com/l/meetup-join/abc",
            "received_time": "2026-09-08T12:00:00Z",
        }
    ]
    test_coordinator.storage.upsert_application("Chrono24", "Senior Java Developer")
    test_coordinator.email_engine.adapters = [MockEmailAdapter(test_emails)]

    # Cycle 1
    res1 = test_coordinator.run_autonomous_cycle(email_limit=5)
    assert res1["requires_human_decision"] is True
    assert len(test_coordinator.storage.list_interviews()) == 1
    assert test_coordinator.storage.get_statistics()["total_applications"] == 1

    # Cycle 2
    res2 = test_coordinator.run_autonomous_cycle(email_limit=5)
    assert len(test_coordinator.storage.list_interviews()) == 1
    assert test_coordinator.storage.get_statistics()["total_applications"] == 1

    # Cycle 3
    res3 = test_coordinator.run_autonomous_cycle(email_limit=5)
    assert len(test_coordinator.storage.list_interviews()) == 1
    assert test_coordinator.storage.get_statistics()["total_applications"] == 1


def test_coordinator_no_provider_creds_llm_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """F4 VP4: coordinator built with no provider creds -> llm_available is False, and
    run_autonomous_cycle completes via the deterministic path WITHOUT attempting an
    agent LLM call."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

    db_path = tmp_path / "no_creds.db"
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    config = AppConfig(
        agent=AgentConfig(provider="gemini", model="gemini-3.8-flash", temperature=0.1),
        storage=StorageConfig(database_path=str(db_path)),
        reporting=ReportingConfig(output_dir=str(out_dir), enable_pdf_export=False),
    )
    storage = JobAgentStorage(str(db_path))
    profile = CandidateProfile(
        personal=PersonalInfo(fullName="Test Candidate", email="candidate@test.com")
    )
    coordinator = JobAgentCoordinator(config=config, storage=storage, profile=profile)

    assert coordinator.llm_available is False

    # A Mock agent that raises if called — proves the LLM branch is never entered.
    class ExplodingAgent:
        name = "JobAgent"

        def __call__(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("agent LLM call must not be attempted without credentials")

    coordinator.agent = ExplodingAgent()  # type: ignore[assignment]

    test_emails = [
        {
            "entry_id": "test_no_llm_1",
            "sender_name": "Acme Corp",
            "sender_email": "jobs@acme.com",
            "subject": "Ihre Bewerbung bei Acme Corp",
            "body": "Vielen Dank für Ihre Bewerbung. Ihre Unterlagen sind eingegangen.",
            "received_time": "2026-09-09T09:00:00Z",
        }
    ]
    coordinator.storage.upsert_application("Acme Corp", "Backend Developer")
    coordinator.email_engine.adapters = [MockEmailAdapter(test_emails)]

    cycle_res = coordinator.run_autonomous_cycle(email_limit=5)
    assert cycle_res["agent_ok"] is False
    assert cycle_res["triage_summary"]["total_scanned"] == 1
    assert cycle_res["triage_summary"]["confirmations_found"] == 1
    assert cycle_res["agent_briefing"] is not None

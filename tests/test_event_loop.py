"""Tests for the EventLoopAgent: autonomous agent loop, honest fallback, and
proves the Strands agent performs the work via TOOL CALLS (not JSON script)."""

import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, ".")  # ensure project root on path

from src.agent.event_loop import EventLoopAgent, THRESHOLD_CONFIDENCE
from src.agent.coordinator import JobAgentCoordinator
from src.core.config import AppConfig, AgentConfig, StorageConfig, ReportingConfig
from src.core.profile import CandidateProfile, PersonalInfo
from src.core.storage import JobAgentStorage
from src.tools.email.adapters import MockEmailAdapter


def _make_coordinator(tmp_path: Path, llm_available: bool) -> JobAgentCoordinator:
    db_path = tmp_path / "evt.db"
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = AppConfig(
        agent=AgentConfig(provider="gemini", model="", temperature=0.1),
        storage=StorageConfig(database_path=str(db_path)),
        reporting=ReportingConfig(output_dir=str(out_dir), enable_pdf_export=False),
    )
    cfg.email_ingestion.llm_fallback = False  # keep tests hermetic, no live Gemini
    storage = JobAgentStorage(str(db_path))
    profile = CandidateProfile(personal=PersonalInfo(fullName="Test User", email="t@t.de"))
    coord = JobAgentCoordinator(config=cfg, storage=storage, profile=profile)
    coord.llm_available = llm_available
    coord.storage.upsert_application("FutureTech GmbH", "Senior Engineer")
    # Simulate an inbox with one new email.
    coord.email_engine.adapters = [
        MockEmailAdapter(
            [
                {
                    "entry_id": "delta_1",
                    "sender_name": "FutureTech HR",
                    "sender_email": "jobs@futuretech.de",
                    "subject": "Einladung zum Vorstellungsgespräch",
                    "body": "Wir laden Sie zu einem Videointerview ein via Teams https://teams.microsoft.com/l/meetup-join/abc",
                    "received_time": "2026-09-20T09:00:00Z",
                }
            ]
        )
    ]
    return coord


def test_offline_mode_is_loud_and_updates_db(tmp_path: Path):
    """No LLM -> the loop still ingests new emails into the CRM but flags agent_ok=False."""
    coord = _make_coordinator(tmp_path, llm_available=False)
    loop = EventLoopAgent(coordinator=coord, poll_seconds=10)

    state = loop.wake()
    assert state["new_email_count"] == 1

    outcome = loop.agent_turn(state)
    loop.record_cycle(state, outcome)

    assert outcome["agent_ok"] is False
    assert "[offline]" in outcome["briefing"]
    # DB currency: the interview was recorded.
    interviews = coord.storage.list_interviews()
    assert len(interviews) == 1
    # Approval surfaced for the human to react.
    pending = coord.storage.list_pending_approvals(status="pending")
    assert len(pending) >= 1
    # Watermark advanced: a second wake sees no new emails.
    state2 = loop.wake()
    assert state2["new_email_count"] == 0


def test_online_mode_agent_drives_via_tool_calls(tmp_path: Path, monkeypatch):
    """When LLM is available the Strands agent itself calls the registered tools.
    We stub the agent with a callable that invokes the ingest tool and returns a
    briefing — proving the loop lets the agent do the job (not a script)."""
    coord = _make_coordinator(tmp_path, llm_available=True)

    # Find the ingest_emails tool the Strands agent would call.
    ingest_tool = next(
        t for t in coord.tools
        if (getattr(t, "tool_name", "") or getattr(t, "__name__", "")) == "ingest_emails"
    )

    class FakeStrandsAgent:
        name = "JobAgent"
        model = object()  # truthy -> loop enters the LLM branch

        def __call__(self, mission: str):
            # The AGENT (stub) chooses to call the ingest tool during its turn,
            # exactly like a real LLM would emit toolUse.
            if "ingest_emails" in mission:
                result = json.loads(ingest_tool(limit=10))
                assert result["interviews_found"] == 1
                # Verify the tool mutation landed in coordinator state.
                assert coord.latest_triage["interviews_found"] == 1
            return SimpleNamespace(message={"content": [{"text": "Processed 1 new application email — interview invite detected."}]})

    from types import SimpleNamespace
    loop = EventLoopAgent(coordinator=coord, poll_seconds=10)
    loop.agent = FakeStrandsAgent()

    state = loop.wake()
    outcome = loop.agent_turn(state)
    loop.record_cycle(state, outcome)

    assert outcome["agent_ok"] is True
    assert "interview" in outcome["briefing"].lower()
    # The agent's tool call actually persisted the interview + approval.
    assert len(coord.storage.list_interviews()) == 1
    assert coord.latest_triage["interviews_found"] == 1


def test_watermark_idempotent_no_duplicate_ingest(tmp_path: Path):
    """A repeated loop iteration must not double-process the same email."""
    coord = _make_coordinator(tmp_path, llm_available=False)
    loop = EventLoopAgent(coordinator=coord, poll_seconds=10)

    for _ in range(2):
        state = loop.wake()
        outcome = loop.agent_turn(state)
        loop.record_cycle(state, outcome)

    assert len(coord.storage.list_interviews()) == 1  # not 2


def test_channel_consumer_domains_externalized():
    """CONSUMER_DOMAINS must come from resources, not inline Python."""
    import importlib
    import src.core.channel_extractor as ce
    importlib.reload(ce)
    assert "gmail.com" in ce.CONSUMER_DOMAINS
    assert ce.extract_channel_from_domain("gmail.com") is None  # generic provider
    assert ce.extract_channel_from_domain("ashbyhq.com") == "Ashby"


def test_legal_keywords_externalized():
    """Form sensitive keywords must load from resources JSON, not inline."""
    from src.tools.form.reasoner import _load_legal_keywords
    kw = _load_legal_keywords()
    assert "citizenship" in kw
    assert "salary" in kw
    # And the classifier ATS domains come from the rules resource, not code.
    from src.tools.email.classifier import EmailClassifier, _load_classification_rules
    rules = _load_classification_rules()
    assert "personio.de" in rules.get("known_ats_domains", [])
    assert "greenhouse.io" in rules.get("known_ats_domains", [])


def test_config_model_names_not_in_code():
    """LLM model/provider names live in config JSON, not as code defaults."""
    from src.core.config import AgentConfig
    defaults = AgentConfig()
    assert defaults.provider == ""
    assert defaults.model == ""
    assert "gemini-3.8-flash" not in defaults.model

def test_batched_llm_classification_single_call(tmp_path: Path, monkeypatch):
    """Ambiguous emails are classified in ONE batched LLM call (rate-limit fix)."""
    from src.tools.email.clustering import ApplicationClusterer
    from src.core.config import AppConfig, EmailIngestionConfig
    import src.tools.email.clustering as clustering_mod

    db_path = tmp_path / "batch.db"
    storage = JobAgentStorage(str(db_path))
    # Ambiguous career-context emails that rules score low-confidence.
    records = [
        MockEmailAdapter([{
            "entry_id": f"amb_{i}",
            "sender_name": f"Sender {i}",
            "sender_email": f"recruiter{i}@someco.de",
            "subject": "Positionsbezogenes Gespräch über Ihr Profil",
            "body": "Wir hätten gerne ein unverbindliches Gespräch zu Ihrer Bewerbung im Bereich Softwareentwicklung.",
            "received_time": "2026-09-21T09:0{i}:00Z",
        }]).fetch_emails()[0]
        for i in range(3)
    ]

    call_counter = {"n": 0}

    def fake_call_gemini(prompt: str) -> str:
        call_counter["n"] += 1
        import json as _json
        return _json.dumps([
            {"entry_id": "amb_0", "category": "follow_up", "confidence": 0.9, "reasoning": "recruiter inquiry"},
            {"entry_id": "amb_1", "category": "follow_up", "confidence": 0.9, "reasoning": "recruiter inquiry"},
            {"entry_id": "amb_2", "category": "noise", "confidence": 0.9, "reasoning": "sales pitch"},
        ])

    monkeypatch.setattr("src.core.llm_provider.call_gemini_semantic_analysis", fake_call_gemini)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    clusterer = ApplicationClusterer(storage=storage)
    res = clusterer.cluster_batch(records, folder="Bewerbung", enable_llm_fallback=True)

    assert call_counter["n"] == 1  # ONE call for the whole ambiguous batch
    assert res["total_processed"] == 3
    assert len(clusterer._batch_llm_results) >= 3
    # The batched results are reused (no per-email LLM calls).
    assert clusterer._batch_llm_results["amb_0"].category == "follow_up"
    assert clusterer._batch_llm_results["amb_2"].category == "noise"

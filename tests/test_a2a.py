"""Tests for A2A Interface, FastAPI Gateway, and FastMCP Server."""

from pathlib import Path
from fastapi.testclient import TestClient

from src.a2a.server import create_a2a_app
from src.core.config import AppConfig
from src.core.profile import CandidateProfile, PersonalInfo
from src.core.storage import JobAgentStorage
from src.a2a.mcp_server import mcp


def test_a2a_server_endpoints(tmp_path: Path):
    db_path = tmp_path / "test_a2a.db"
    storage = JobAgentStorage(db_path=str(db_path))

    # Seed data
    storage.upsert_application(
        company="A2A Robotics",
        role="Agent Engineer",
        applied_date="2026-09-08T10:00:00Z",
        status="Interview",
    )
    storage.save_qa_answer("What is your citizenship?", "EU Citizen", "legal")

    profile = CandidateProfile(
        personal=PersonalInfo(
            fullName="Alex Agent",
            email="alex@agent.ai",
        )
    )

    test_token = "test-secret-token-12345"
    app = create_a2a_app(storage=storage, profile=profile, api_token=test_token)
    # F3: gateway validates the Host header — tests must address it via a
    # loopback/config host (explicit base_url), never the TestClient default
    # 'testserver' (which the middleware correctly rejects).
    client = TestClient(app, base_url="http://127.0.0.1:8765")

    # 1. Health check (public probe: verifies agent is healthy without exposing credentials)
    res_health = client.get("/health")
    assert res_health.status_code == 200
    health_data = res_health.json()
    assert health_data["status"] == "ok"
    assert "token" not in health_data
    token = test_token

    # 2. Verify unauthorized request is rejected
    unauth_res = client.get("/a2a/v1/capabilities")
    assert unauth_res.status_code == 401

    # Attach Authorization Bearer token header for authenticated calls
    auth_headers = {"Authorization": f"Bearer {token}"}

    # 3. Capabilities discovery
    res_cap = client.get("/a2a/v1/capabilities", headers=auth_headers)
    assert res_cap.status_code == 200
    caps = res_cap.json()
    assert len(caps) >= 5
    assert any(c["id"] == "triage_emails" for c in caps)

    # 4. Status query
    res_status = client.get("/a2a/v1/status", headers=auth_headers)
    assert res_status.status_code == 200
    status_data = res_status.json()
    assert status_data["statistics"]["total_applications"] == 1

    # 4b. Verify query string token ?token= is rejected (P1 security fix)
    query_token_res = client.get(f"/a2a/v1/status?token={token}")
    assert query_token_res.status_code == 401

    # 4c. Verify GET /dashboard serves clean HTML dashboard
    dash_res = client.get("/dashboard")
    assert dash_res.status_code == 200
    assert "text/html" in dash_res.headers["content-type"]
    assert "JobAgent Career Analytics" in dash_res.text

    # 5. Delegate task: get_status
    task_payload = {
        "source_agent": "hermes",
        "action": "get_status",
        "payload": {},
    }
    res_task = client.post("/a2a/v1/tasks", json=task_payload, headers=auth_headers)
    assert res_task.status_code == 200
    task_res = res_task.json()
    assert task_res["status"] == "completed"
    assert "statistics" in task_res["result"]

    # 6. Delegate task: query_qa
    qa_payload = {
        "source_agent": "openclaw",
        "action": "query_qa",
        "payload": {"question": "citizenship"},
    }
    res_qa = client.post("/a2a/v1/tasks", json=qa_payload, headers=auth_headers)
    assert res_qa.status_code == 200
    assert res_qa.json()["result"]["answer"] == "EU Citizen"

    # 7. Extension API profile
    res_prof = client.get("/api/v1/profile", headers=auth_headers)
    assert res_prof.status_code == 200
    assert res_prof.json()["personal"]["fullName"] == "Alex Agent"

    # 8. Document bundle endpoint
    res_docs = client.get("/api/v1/documents/bundle", headers=auth_headers)
    assert res_docs.status_code == 200
    assert isinstance(res_docs.json(), dict)

    # 9. Cover letter generation endpoint
    cl_payload = {
        "company": "Capgemini",
        "role": "Cloud Architect",
        "lang": "en",
    }
    res_cl = client.post("/api/v1/cover_letter/generate", json=cl_payload, headers=auth_headers)
    assert res_cl.status_code == 200
    cl_data = res_cl.json()
    assert cl_data["company"] == "Capgemini"
    assert "pdf_path" in cl_data


# ---------------------------------------------------------------------------
# F3: Gateway auth hardening — Host header validation (DNS rebinding), loopback
# enforcement on /api/v1/auth/pair, and Docker loopback binding.


def _make_f3_app(tmp_path: Path, test_token: str = "test-secret-token-12345"):
    db_path = tmp_path / "f3_a2a.db"
    storage = JobAgentStorage(db_path=str(db_path))
    profile = CandidateProfile(
        personal=PersonalInfo(fullName="Alex Agent", email="alex@agent.ai")
    )
    app = create_a2a_app(storage=storage, profile=profile, api_token=test_token)
    return app, storage, profile, test_token


def test_host_header_dns_rebinding_rejected(tmp_path: Path):
    """F3 VP1: Host: evil.example.com → 403 on pair AND on authenticated routes."""
    app, _storage, _profile, test_token = _make_f3_app(tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    evil = {"Host": "evil.example.com"}

    # Unauthenticated pair endpoint must refuse to hand out the token
    res = client.get("/api/v1/auth/pair", headers=evil)
    assert res.status_code == 403
    assert res.json()["detail"] == "Invalid Host header"

    # Authenticated route with a VALID token must also be refused
    res = client.get(
        "/api/v1/profile",
        headers={**evil, "Authorization": f"Bearer {test_token}"},
    )
    assert res.status_code == 403

    # A2A route as well
    res = client.get(
        "/a2a/v1/capabilities",
        headers={**evil, "Authorization": f"Bearer {test_token}"},
    )
    assert res.status_code == 403


def test_host_header_loopback_allowed_pair_returns_token(tmp_path: Path):
    """F3 VP1: Host: 127.0.0.1:8765 (TestClient base_url) → pair returns token."""
    app, _storage, _profile, test_token = _make_f3_app(tmp_path)
    # Loopback client IP: the pair endpoint independently requires it.
    client = TestClient(
        app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000)
    )

    res = client.get("/api/v1/auth/pair")
    assert res.status_code == 200
    assert res.json()["token"] == test_token
    assert res.json()["status"] == "paired"

    # Auth'd route still works with a valid loopback Host
    auth = {"Authorization": f"Bearer {test_token}"}
    res = client.get("/api/v1/profile", headers=auth)
    assert res.status_code == 200
    assert res.json()["personal"]["fullName"] == "Alex Agent"


def test_host_header_localhost_and_ipv6_variants_allowed(tmp_path: Path):
    """F3: localhost[:port] and [::1][:port] Host variants are accepted."""
    app, _storage, _profile, _test_token = _make_f3_app(tmp_path)
    client = TestClient(
        app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50001)
    )

    for host in (
        "localhost",
        "localhost:8765",
        "[::1]",
        "[::1]:8765",
        "127.0.0.1",
        "127.0.0.1:8765",
    ):
        res = client.get("/api/v1/auth/pair", headers={"Host": host})
        assert res.status_code == 200, f"Host {host!r} should be allowed"


def test_host_header_configured_a2a_host_allowed(tmp_path: Path):
    """F3: configured cfg.a2a.host is allowed while evil hosts stay blocked."""
    db_path = tmp_path / "f3_cfg.db"
    storage = JobAgentStorage(db_path=str(db_path))
    profile = CandidateProfile(
        personal=PersonalInfo(fullName="Alex Agent", email="alex@agent.ai")
    )
    cfg = AppConfig()
    cfg.a2a.host = "a2a.internal"
    app = create_a2a_app(config=cfg, storage=storage, profile=profile, api_token="tok1")
    # Loopback client IP so the pair endpoint's own loopback check passes; the
    # Host-header is what we are testing here.
    client = TestClient(
        app, base_url="http://a2a.internal:8765", client=("127.0.0.1", 5555)
    )

    assert client.get("/api/v1/auth/pair").status_code == 200
    res = client.get("/api/v1/auth/pair", headers={"Host": "evil.example.com"})
    assert res.status_code == 403


def test_auth_pair_rejects_non_loopback_client(tmp_path: Path):
    """F3 VP1: existing loopback client-IP check on pair is preserved."""
    app, _storage, _profile, _test_token = _make_f3_app(tmp_path)
    client = TestClient(
        app, base_url="http://127.0.0.1:8765", client=("203.0.113.7", 54321)
    )

    res = client.get("/api/v1/auth/pair")
    assert res.status_code == 403
    assert "loopback" in res.json()["detail"]


def test_delegate_task_unknown_action_returns_400(tmp_path: Path):
    """F6 VP3: POST /a2a/v1/tasks with an unknown action -> HTTP 400, not a swallowed 200."""
    app, _storage, _profile, test_token = _make_f3_app(tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    auth_headers = {"Authorization": f"Bearer {test_token}"}

    payload = {
        "source_agent": "hermes",
        "action": "bogus",
        "payload": {},
    }
    res = client.post("/a2a/v1/tasks", json=payload, headers=auth_headers)
    assert res.status_code == 400
    assert "bogus" in res.json()["detail"]


def test_mcp_server_tools_registered():
    import asyncio
    tools = asyncio.run(mcp.list_tools())
    tool_names = [t.name for t in tools]
    assert "jobagent_triage_inbox" in tool_names
    assert "jobagent_archive_posting" in tool_names
    assert "jobagent_get_interviews" in tool_names
    assert "jobagent_generate_compliance_report" in tool_names
    assert "jobagent_query_qa_memory" in tool_names


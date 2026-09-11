"""Tests for A2A Interface, FastAPI Gateway, and FastMCP Server."""

from pathlib import Path
from fastapi.testclient import TestClient

from src.a2a.server import create_a2a_app
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
    client = TestClient(app)

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


def test_mcp_server_tools_registered():
    import asyncio
    tools = asyncio.run(mcp.list_tools())
    tool_names = [t.name for t in tools]
    assert "jobagent_triage_inbox" in tool_names
    assert "jobagent_archive_posting" in tool_names
    assert "jobagent_get_interviews" in tool_names
    assert "jobagent_generate_compliance_report" in tool_names
    assert "jobagent_query_qa_memory" in tool_names


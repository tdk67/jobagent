"""FastAPI HTTP and SSE server exposing the A2A (Agent-to-Agent) Interface and Extension API."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

ROBOTS_TXT = """User-agent: *
Allow: /
Disallow: /api/
Disallow: /a2a/v1/tasks
Disallow: /a2a/v1/events
"""

LLMS_TXT = """# JobAgent
> Autonomous Background Career CRM & Statutory Compliance Engine

JobAgent is a local-first AI career agent built with the AWS Strands Agents SDK. It automates job application tracking, dual-asset posting archiving (Markdown + high-resolution PDF snapshots), multi-protocol email triage, and official statutory reporting (German Agentur für Arbeit Eigenbemühungsnachweis, § 138 SGB III).

## Interfaces & Protocols
- Model Context Protocol (MCP): Native FastMCP tools via `python run_agent.py --mcp` or stdio.
- Agent-to-Agent (A2A) REST & SSE Gateway: Running on http://127.0.0.1:8765.
- Browser Copilot Extension: Chrome/Edge Manifest V3 extension for 1-click archiving and smart form assist.

## Key Endpoints
- GET /health : Service health status.
- GET /llms.txt : Agent overview and capability specifications.
- GET /.well-known/llms.txt : Standard AI discovery manifest.
- GET /robots.txt : Web crawler access policies.
- GET /a2a/v1/capabilities : Dynamic JSON schema of agent capabilities and tools (Authenticated).
- POST /a2a/v1/tasks : Delegate asynchronous or synchronous tasks to JobAgent (Authenticated).
- GET /a2a/v1/events : Real-time Server-Sent Events (SSE) stream for actionable alerts (Authenticated).

## Available Tools
- jobagent_triage_inbox: Scans connected inboxes (Desktop Outlook MAPI, Gmail MCP, generic IMAP). Supports start_date and end_date parameters to process emails week-by-week.
- jobagent_archive_posting: Archives job URL or raw HTML into clean Markdown and high-res PDF snapshot.
- jobagent_get_interviews: Retrieves scheduled hiring interviews, notes, and verified meeting links.
- jobagent_generate_compliance_report: Compiles official statutory proof tables (German AfA table) or KPI dashboards. Supports start_date, end_date, and weekly parameters.
- jobagent_query_qa_memory: Retrieves verified candidate answers for screening questions.

## Privacy & Security Guarantees
- Zero Cloud Database: All application data and candidate profile records are stored strictly in local SQLite (`data/jobagent.db`).
- Authentication: Token-based via `Authorization: Bearer <token>` or `X-JobAgent-Token: <token>`.
"""


from src.a2a.protocol import A2ACapability, A2AEvent, TaskEnvelope, TaskResponse
from src.core.config import AppConfig, load_config
from src.core.profile import CandidateProfile, load_profile
from src.core.storage import JobAgentStorage
from src.tools.email_ingest_tool import EmailIngestEngine
from src.tools.form.reasoner import FormReasoner
from src.tools.job_archive_tool import JobArchiveEngine
from src.tools.report_render_tool import ReportRenderEngine

log = logging.getLogger(__name__)
security_bearer = HTTPBearer(auto_error=False)


def create_a2a_app(
    config: Optional[AppConfig] = None,
    storage: Optional[JobAgentStorage] = None,
    profile: Optional[CandidateProfile] = None,
    api_token: Optional[str] = None,
) -> FastAPI:
    cfg = config or load_config()
    db = storage or JobAgentStorage(cfg.storage.database_path)
    user_profile = profile or load_profile()

    active_token = api_token or os.getenv("JOBAGENT_API_TOKEN")
    if not active_token:
        token_file = Path(".jobagent_token")
        if token_file.exists():
            try:
                active_token = token_file.read_text(encoding="utf-8").strip()
            except Exception:
                active_token = None
        if not active_token:
            active_token = secrets.token_hex(16)
            try:
                token_file.write_text(active_token, encoding="utf-8")
            except Exception as e:
                log.warning("Could not persist token to .jobagent_token: %s", e)

    log.info("JobAgent API Token: %s", active_token)
    print(f"\n🔑 JobAgent API Token: {active_token}")
    print(f"   (Persisted in .jobagent_token for browser extension & CLI)\n")

    def verify_token(
        credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
        x_token: Optional[str] = Header(None, alias="X-JobAgent-Token"),
        token: Optional[str] = Query(None, alias="token"),
    ) -> bool:
        supplied = None
        if credentials and credentials.credentials:
            supplied = credentials.credentials
        elif x_token:
            supplied = x_token
        elif token:
            supplied = token

        if not supplied or not secrets.compare_digest(supplied, active_token):
            raise HTTPException(
                status_code=401,
                detail="Unauthorized: Invalid or missing API token",
            )
        return True

    email_engine = EmailIngestEngine(storage=db, config=cfg)
    archive_engine = JobArchiveEngine(storage=db, config=cfg)
    report_engine = ReportRenderEngine(storage=db, profile=user_profile, config=cfg)
    form_reasoner = FormReasoner(storage=db, profile=user_profile, config=cfg)

    app = FastAPI(
        title="JobAgent A2A Gateway",
        description="Agent-to-Agent interface and browser copilot API for JobAgent",
        version="1.0.0",
    )
    app.state.api_token = active_token

    # Secure CORS configuration: Restrict origins derived from active config
    allowed_origins = [
        f"http://{cfg.a2a.host}:{cfg.a2a.port}",
        f"http://localhost:{cfg.a2a.port}",
        f"http://127.0.0.1:{cfg.a2a.port}",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_origin_regex=r"^chrome-extension://[a-z]+$",
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # In-memory queue for SSE event broadcast
    event_subscribers: List[asyncio.Queue] = []

    async def broadcast_event(event: A2AEvent) -> None:
        for q in list(event_subscribers):
            try:
                await q.put(event)
            except Exception as e:
                log.warning("Dropping disconnected SSE subscriber: %s", e)
                if q in event_subscribers:
                    event_subscribers.remove(q)

    # 1. Health & Discovery (Public probes)
    @app.get("/health")
    async def health() -> Dict[str, str]:
        return {
            "status": "ok",
            "agent": "JobAgent",
            "version": "1.0.0",
        }

    @app.get("/robots.txt", response_class=PlainTextResponse)
    async def get_robots_txt() -> str:
        return ROBOTS_TXT

    @app.get("/llms.txt", response_class=PlainTextResponse)
    @app.get("/.well-known/llms.txt", response_class=PlainTextResponse)
    async def get_llms_txt() -> str:
        return LLMS_TXT


    @app.get("/a2a/v1/capabilities", dependencies=[Depends(verify_token)])
    async def get_capabilities() -> List[A2ACapability]:
        return [
            A2ACapability(
                id="triage_emails",
                name="Triage Inbox Emails",
                description="Scans incoming emails, classifies into applications/interviews/rejections, and updates CRM.",
                parameters_schema={"limit": {"type": "integer", "default": 50}},
                returns_schema={"total_scanned": "int", "interviews_found": "int"},
            ),
            A2ACapability(
                id="archive_job",
                name="Archive Job Posting",
                description="Preserves posting as clean Markdown and high-resolution PDF snapshot.",
                parameters_schema={
                    "company": {"type": "string"},
                    "role": {"type": "string"},
                    "job_url": {"type": "string", "optional": True},
                    "raw_html": {"type": "string", "optional": True},
                },
                returns_schema={"markdown_path": "string", "snapshot_pdf_path": "string"},
            ),
            A2ACapability(
                id="generate_compliance_report",
                name="Generate Compliance Report",
                description="Renders candidate dashboard, headhunter summary, or official German Agentur für Arbeit proof table.",
                parameters_schema={
                    "report_type": {"type": "string", "enum": ["dashboard", "afa_table", "agency_summary"]}
                },
                returns_schema={"html_path": "string", "pdf_path": "string"},
            ),
            A2ACapability(
                id="get_status",
                name="Get Application Status",
                description="Returns total applications, response rates, and active interviews.",
            ),
            A2ACapability(
                id="query_qa",
                name="Query Screening Q&A Memory",
                description="Retrieves candidate's verified screening question answer.",
                parameters_schema={"question": {"type": "string"}},
                returns_schema={"answer": "string"},
            ),
        ]

    # 2. Task Delegation Endpoint
    @app.post("/a2a/v1/tasks", response_model=TaskResponse, dependencies=[Depends(verify_token)])
    async def delegate_task(envelope: TaskEnvelope, background_tasks: BackgroundTasks) -> TaskResponse:
        action = envelope.action.lower()
        payload = envelope.payload

        try:
            if action == "triage_emails":
                limit = payload.get("limit", 50)
                res = email_engine.run_triage(limit=limit)

                # Broadcast actionable alert if interview was detected
                if res.get("interviews_found", 0) > 0:
                    for alert in res.get("actionable_alerts", []):
                        event = A2AEvent(
                            event_type="interview_detected",
                            priority="high",
                            payload=alert,
                        )
                        background_tasks.add_task(broadcast_event, event)

                return TaskResponse(
                    task_id=envelope.task_id,
                    status="completed",
                    result=res,
                )

            elif action == "archive_job":
                res = archive_engine.archive(
                    company=payload.get("company", "Unknown Company"),
                    role=payload.get("role", "Software Engineer"),
                    job_url=payload.get("job_url"),
                    raw_html=payload.get("raw_html"),
                    qa_pairs=payload.get("qa_pairs"),
                )
                artifacts = []
                if res.get("snapshot_pdf_path"):
                    artifacts.append(res["snapshot_pdf_path"])
                if res.get("markdown_path"):
                    artifacts.append(res["markdown_path"])

                return TaskResponse(
                    task_id=envelope.task_id,
                    status="completed",
                    result=res,
                    artifacts=artifacts,
                )

            elif action == "generate_compliance_report":
                report_type = payload.get("report_type", "dashboard")
                res = report_engine.generate(view_type=report_type, export_pdf=True)
                artifacts = []
                if res.get("pdf_path"):
                    artifacts.append(res["pdf_path"])
                if res.get("html_path"):
                    artifacts.append(res["html_path"])

                return TaskResponse(
                    task_id=envelope.task_id,
                    status="completed",
                    result=res,
                    artifacts=artifacts,
                )

            elif action == "get_status":
                stats = db.get_statistics()
                interviews = db.list_interviews()
                return TaskResponse(
                    task_id=envelope.task_id,
                    status="completed",
                    result={"statistics": stats, "interviews": interviews},
                )

            elif action == "query_qa":
                q = payload.get("question", "")
                ans = db.get_qa_answer(q)
                return TaskResponse(
                    task_id=envelope.task_id,
                    status="completed",
                    result={"question": q, "answer": ans},
                )

            else:
                raise HTTPException(status_code=400, detail=f"Unknown A2A action: {action}")

        except Exception as err:
            log.warning("Task execution failed for action %s: %s", action, err, exc_info=True)
            return TaskResponse(
                task_id=envelope.task_id,
                status="failed",
                error=str(err),
            )

    # 3. Status & Analytics
    @app.get("/a2a/v1/status", dependencies=[Depends(verify_token)])
    async def get_agent_status() -> Dict[str, Any]:
        return {
            "statistics": db.get_statistics(),
            "interviews": db.list_interviews(),
            "recent_applications": db.list_applications(limit=5),
        }

    # 4. SSE Real-Time Event Stream for Parent Personal Agents
    @app.get("/a2a/v1/events", dependencies=[Depends(verify_token)])
    async def sse_events(request: Request) -> StreamingResponse:
        queue: asyncio.Queue = asyncio.Queue()
        event_subscribers.append(queue)

        async def event_generator() -> AsyncGenerator[str, None]:
            try:
                # Send initial connection event
                yield f"data: {json.dumps({'event': 'connected', 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event: A2AEvent = await asyncio.wait_for(queue.get(), timeout=15.0)
                        yield f"event: {event.event_type}\ndata: {json.dumps(event.model_dump())}\n\n"
                    except asyncio.TimeoutError:
                        # Keep-alive heartbeat
                        yield ": keepalive\n\n"
            finally:
                if queue in event_subscribers:
                    event_subscribers.remove(queue)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # 5. Extension API Endpoints (Decoupled, zero hardcoded PII)
    @app.get("/api/v1/auth/pair")
    async def auto_pair_extension(request: Request) -> Dict[str, str]:
        """Allows automatic pairing for the local browser extension on loopback."""
        client_host = request.client.host if request.client else ""
        if client_host not in ("127.0.0.1", "localhost", "::1"):
            raise HTTPException(status_code=403, detail="Auto-pairing only allowed from local loopback")
        return {"token": active_token, "status": "paired"}

    @app.get("/api/v1/profile", dependencies=[Depends(verify_token)])
    async def get_extension_profile() -> Dict[str, Any]:
        """Provides candidate profile dynamically to the browser extension."""
        return user_profile.model_dump()

    @app.post("/api/v1/archive", dependencies=[Depends(verify_token)])
    async def extension_archive_job(payload: Dict[str, Any]) -> Dict[str, Any]:
        """1-click archive endpoint called from Chrome extension popup."""
        res = archive_engine.archive(
            company=payload.get("company", "Unknown Company"),
            role=payload.get("role", "Software Engineer"),
            job_url=payload.get("url"),
            raw_html=payload.get("html"),
        )
        return res

    @app.get("/api/v1/qa", dependencies=[Depends(verify_token)])
    async def extension_query_qa(question: str) -> Dict[str, Any]:
        ans = db.get_qa_answer(question)
        return {"question": question, "answer": ans}

    @app.post("/api/v1/form/reason", dependencies=[Depends(verify_token)])
    async def reason_form_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Whole-form semantic reasoning endpoint using Gemini 3.8 Flash & QA memory."""
        fields = payload.get("fields", [])
        page_url = payload.get("url")
        return form_reasoner.reason_form(fields=fields, page_url=page_url)

    @app.post("/api/v1/form/learn", dependencies=[Depends(verify_token)])
    async def learn_form_field(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Continuous learning endpoint: persists newly answered question into QA memory."""
        q = payload.get("question", "").strip()
        a = payload.get("answer", "").strip()
        cat = payload.get("category", "user_taught")
        if q and a:
            db.save_qa_answer(question_text=q, answer=a, category=cat, verified=1)
            return {"status": "ok", "question": q, "saved": True}
        raise HTTPException(status_code=400, detail="Missing question or answer")

    @app.get("/api/v1/form/memory", dependencies=[Depends(verify_token)])
    async def get_qa_memory() -> Dict[str, Any]:
        """Returns all currently stored QA memory entries."""
        return {"memory": db.list_qa_memory()}

    @app.get("/api/v1/documents/bundle", dependencies=[Depends(verify_token)])
    async def get_document_bundle() -> Dict[str, Any]:
        """Provides base64 data URLs for user's CV, cover letter, and references for browser extension upload."""
        docs = user_profile.documents
        bundle: Dict[str, Any] = {}

        # 1. CV (German preferred, fallback English)
        cv_path = docs.germanCv or docs.englishCv
        if cv_path and Path(cv_path).exists():
            p = Path(cv_path)
            content = p.read_bytes()
            bundle["cv"] = {
                "filename": p.name,
                "dataUrl": f"data:application/pdf;base64,{base64.b64encode(content).decode('ascii')}",
                "sizeBytes": len(content),
            }

        # 2. Cover Letter
        cl_path = docs.coverLetter
        if cl_path and Path(cl_path).exists():
            p = Path(cl_path)
            content = p.read_bytes()
            bundle["coverLetter"] = {
                "filename": p.name,
                "dataUrl": f"data:application/pdf;base64,{base64.b64encode(content).decode('ascii')}",
                "sizeBytes": len(content),
            }

        # 3. Reference Letter
        ref_path = docs.referenceLetter
        if ref_path and Path(ref_path).exists():
            p = Path(ref_path)
            content = p.read_bytes()
            bundle["reference"] = {
                "filename": p.name,
                "dataUrl": f"data:application/pdf;base64,{base64.b64encode(content).decode('ascii')}",
                "sizeBytes": len(content),
            }

        return bundle

    @app.post("/api/v1/cover_letter/generate", dependencies=[Depends(verify_token)])
    async def generate_cover_letter_api(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Generates a DIN 5008 cover letter for a given company and job role."""
        company = payload.get("company", "Unternehmen")
        role = payload.get("role", "Software Engineer")
        lang = payload.get("lang", "de")
        from src.tools.cover_letter_tool import CoverLetterEngine
        engine = CoverLetterEngine()
        return engine.generate(company=company, role=role, lang=lang)

    return app

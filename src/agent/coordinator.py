from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from strands import Agent, tool
from strands.models import BedrockModel

from src.core.config import AppConfig, load_config
from src.core.llm_provider import create_strands_gemini_model
from src.core.profile import CandidateProfile, load_profile
from src.core.storage import JobAgentStorage
from src.tools.email_ingest_tool import EmailIngestEngine
from src.tools.job_archive_tool import JobArchiveEngine
from src.tools.report_render_tool import ReportRenderEngine
from src.utils.prompt_loader import load_prompt

log = logging.getLogger(__name__)


def _load_system_prompt() -> str:
    try:
        return load_prompt("coordinator_system.txt")
    except Exception:
        return """You are JobAgent, an autonomous background career agent built with the AWS Strands Agents SDK.
Your mission is to remove the busywork, stress, and repetitive paperwork from the candidate's career search:
1. Ingest and classify emails across connected inboxes (applications, rejections, genuine interview invitations).
2. Filter out webinars, sales pitches, and deceptive marketing meetings.
3. Preserve dual-asset archives of job postings (clean Markdown + high-res PDF snapshots).
4. Maintain statutory proof tables for government employment compliance (e.g. German Agentur für Arbeit).
5. Only interrupt or escalate to the human candidate when an explicit decision or action is required.
"""


SYSTEM_PROMPT = _load_system_prompt()


class JobAgentCoordinator:
    """Coordinates Strands Agent execution, autonomous background cycles, and tool orchestration."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        storage: Optional[JobAgentStorage] = None,
        profile: Optional[CandidateProfile] = None,
    ):
        self.config = config or load_config()
        self.storage = storage or JobAgentStorage(self.config.storage.database_path)
        self.profile = profile or load_profile()

        self.email_engine = EmailIngestEngine(storage=self.storage, config=self.config)
        self.archive_engine = JobArchiveEngine(storage=self.storage, config=self.config)
        self.report_engine = ReportRenderEngine(storage=self.storage, profile=self.profile, config=self.config)

        self.latest_triage: Dict[str, Any] = {}
        self.latest_reports: Dict[str, Any] = {}

        self.tools = self._build_tools()
        self.agent = self._init_strands_agent()

    def _build_tools(self) -> List[Any]:
        """Builds Strands tools bound to the active coordinator session and engines."""

        @tool(name="ingest_emails", description="Ingests and triages job search emails from connected inboxes.")
        def tool_ingest_emails(limit: int = 50) -> str:
            """Scans connected inboxes, classifies messages into interviews/rejections/confirmations, and records into database.

            Parameters:
                limit: Maximum number of emails to scan.

            Returns:
                A JSON summary of the triage results and any actionable alerts.
            """
            res = self.email_engine.run_triage(limit=limit)
            self.latest_triage = res
            return json.dumps(res, indent=2)

        @tool(name="generate_compliance_report", description="Generates statutory proof tables and visual PDF reports.")
        def tool_generate_compliance_report(report_type: str = "all") -> str:
            """Generates official compliance reports or personal dashboards.

            Parameters:
                report_type: 'all' (all reports), 'dashboard' (KPI overview), 'afa_table' (German Agentur für Arbeit statutory table), or 'agency_summary' (Headhunter list).

            Returns:
                JSON string with paths to generated reports.
            """
            if report_type == "all":
                res = self.report_engine.generate_all_views()
                self.latest_reports = res
                return json.dumps({k: v.get("pdf_path") for k, v in res.items()}, indent=2)
            else:
                res = self.report_engine.generate(view_type=report_type, export_pdf=True)
                self.latest_reports[report_type] = res
                return json.dumps(res, indent=2)

        @tool(name="archive_job_posting", description="Preserves a job posting as clean Markdown and visual PDF snapshot.")
        def tool_archive_job_posting(
            company: str,
            role: str,
            job_url: Optional[str] = None,
            raw_html: Optional[str] = None,
        ) -> str:
            """Archives a job posting into clean Markdown text and full-page PDF snapshot.

            Parameters:
                company: Name of the hiring company.
                role: Title of the position.
                job_url: Web address of the job post.
                raw_html: Optional DOM HTML content of the job post.

            Returns:
                JSON string with paths to the archived assets and CRM entry ID.
            """
            res = self.archive_engine.archive(company=company, role=role, job_url=job_url, raw_html=raw_html)
            return json.dumps(res, indent=2)

        @tool(name="get_pipeline_statistics", description="Returns recruitment funnel metrics and interview counts.")
        def tool_get_pipeline_statistics() -> str:
            """Returns career pipeline KPIs and active interview lists.

            Returns:
                JSON string containing current application funnel counts and interviews.
            """
            stats = self.storage.get_statistics()
            interviews = self.storage.list_interviews()
            return json.dumps({"statistics": stats, "interviews": interviews}, indent=2)

        @tool(name="ask_human_for_approval", description="Requests explicit human confirmation for sensitive or high-impact decisions.")
        def tool_ask_human_for_approval(
            question: str,
            context: str = "",
            urgency: str = "normal",
        ) -> str:
            """Pauses or registers a pending human approval request on the candidate dashboard.

            Parameters:
                question: The specific question or confirmation required from the human candidate.
                context: Background information, company name, meeting times, or action proposal.
                urgency: Priority level ('normal', 'high', 'urgent').

            Returns:
                JSON string with the registered approval request ID and status.
            """
            approval_id = self.storage.create_pending_approval(
                question=question,
                context=context,
                urgency=urgency,
            )
            return json.dumps({
                "approval_id": approval_id,
                "status": "pending_human_review",
                "message": f"Approval request #{approval_id} registered on candidate dashboard."
            }, indent=2)

        return [
            tool_ingest_emails,
            tool_generate_compliance_report,
            tool_archive_job_posting,
            tool_get_pipeline_statistics,
            tool_ask_human_for_approval,
        ]

    def _init_strands_agent(self) -> Agent:
        """Initializes the Strands Agent with session-bound tools and configured model provider.

        Sets ``self.llm_available`` — True only if a provider was explicitly initialized
        with credentials.
        """
        tools = self.tools
        model_obj = None
        llm_available = False

        # 1. Check Gemini Provider
        if self.config.agent.provider == "gemini" and os.getenv("GEMINI_API_KEY"):
            try:
                model_obj = create_strands_gemini_model(config=self.config)
                llm_available = True
                log.info(
                    "Initialized Strands GeminiModel with model %s (temperature=%.2f)",
                    self.config.agent.model,
                    self.config.agent.temperature,
                )
            except Exception as e:
                log.warning("Failed to initialize Strands GeminiModel: %s", e, exc_info=True)
                model_obj = None

        # 2. Check Bedrock Provider (primary or fallback if Gemini missing/failed)
        has_aws_creds = bool(os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"))
        if model_obj is None:
            if (
                self.config.agent.provider == "bedrock"
                or self.config.agent.fallback_provider == "bedrock"
            ) and has_aws_creds:
                try:
                    bedrock_id = (
                        self.config.agent.model
                        if self.config.agent.provider == "bedrock"
                        else self.config.agent.fallback_model
                    )
                    model_obj = BedrockModel(model_id=bedrock_id)
                    llm_available = True
                    log.info("Initialized BedrockModel with model %s", bedrock_id)
                except Exception as e:
                    log.warning("Failed to initialize BedrockModel: %s", e, exc_info=True)
                    model_obj = None

        # 3. Check Ollama Provider (local-first fallback or primary)
        if model_obj is None:
            if (
                self.config.agent.provider == "ollama"
                or self.config.agent.fallback_provider == "ollama"
            ):
                try:
                    from src.core.llm_provider import create_strands_ollama_model
                    ollama_id = (
                        self.config.agent.model
                        if self.config.agent.provider == "ollama"
                        else self.config.agent.fallback_model
                    )
                    model_obj = create_strands_ollama_model(config=self.config, model_id=ollama_id)
                    llm_available = True
                    log.info("Initialized OllamaModel with model %s", ollama_id)
                except ImportError as e:
                    log.warning("Failed to initialize OllamaModel: %s", e)
                    model_obj = None
                except Exception as e:
                    log.warning("Failed to initialize OllamaModel: %s", e, exc_info=True)
                    model_obj = None

        self.llm_available = llm_available
        if not self.llm_available:
            log.warning(
                "No LLM provider configured (set GEMINI_API_KEY or AWS credentials) — "
                "running deterministic tool-only mode"
            )

        try:
            return Agent(
                name="JobAgent",
                model=model_obj,
                tools=tools,
                system_prompt=SYSTEM_PROMPT,
            )
        except Exception as e:
            log.warning("Agent instantiation with model failed, using tool-only agent: %s", e, exc_info=True)
            return Agent(name="JobAgent", tools=tools, system_prompt=SYSTEM_PROMPT)

    def run_autonomous_cycle(self, email_limit: int = 50) -> Dict[str, Any]:
        """Executes an autonomous background cycle: Agent reasons, invokes tools, and briefs candidate."""
        import time
        cycle_id = f"cycle_{int(time.time())}"
        self.storage.record_agent_cycle(cycle_id=cycle_id, status="running")

        self.latest_triage = {}
        self.latest_reports = {}
        agent_briefing: Optional[str] = None
        agent_ok: bool = False

        # Strands Agent autonomous reasoning & tool-dispatch loop
        if self.llm_available and self.agent and getattr(self.agent, "model", None):
            mission = (
                f"Execute autonomous career cycle:\n"
                f"1. Call `ingest_emails` with limit={email_limit} to triage newly received messages and detect interviews/rejections.\n"
                f"2. Call `generate_compliance_report` with report_type='all' to update official statutory compliance proof tables.\n"
                f"3. Provide a clear, professional 1-2 sentence executive briefing for the candidate on what occurred, "
                f"and explicitly highlight if any genuine interview invitations or human action is required."
            )
            try:
                agent_res = self.agent(mission)
                msg = getattr(agent_res, "message", {})
                if isinstance(msg, dict):
                    content = msg.get("content", [])
                    texts = [b.get("text") for b in content if isinstance(b, dict) and "text" in b]
                    agent_briefing = " ".join(filter(None, texts)) or str(agent_res)
                else:
                    agent_briefing = str(agent_res)
                agent_ok = True
            except Exception as e:
                log.warning("Strands Agent autonomous execution failed: %s", e, exc_info=True)
                agent_briefing = f"[Warning: Strands Agent reasoning error: {e}]"
                agent_ok = False

        # Safe fallback: Ensure essential steps ran even if agent tool dispatch was skipped or offline
        if not self.latest_triage:
            log.info("Running deterministic email triage fallback...")
            self.latest_triage = self.email_engine.run_triage(limit=email_limit)

        if not self.latest_reports:
            log.info("Running deterministic report generation fallback...")
            self.latest_reports = self.report_engine.generate_all_views()

        if not agent_briefing:
            agent_briefing = (
                f"[Deterministic Fallback] Processed {self.latest_triage.get('total_scanned', 0)} messages. "
                f"Found {self.latest_triage.get('interviews_found', 0)} interviews, "
                f"{self.latest_triage.get('rejections_found', 0)} rejections."
            )

        stats = self.storage.get_statistics()
        interviews = self.storage.list_interviews()
        actionable_alerts = self.latest_triage.get("actionable_alerts", [])
        requires_human_attention = len(actionable_alerts) > 0

        # Persist final cycle state
        self.storage.record_agent_cycle(
            cycle_id=cycle_id,
            status="completed",
            triage_result=self.latest_triage,
            reports_result=self.latest_reports,
        )

        return {
            "cycle_id": cycle_id,
            "timestamp": self.latest_triage.get("timestamp"),
            "agent_ok": agent_ok,
            "triage_summary": self.latest_triage,
            "reports_generated": {
                k: v.get("pdf_path") for k, v in self.latest_reports.items() if isinstance(v, dict) and v.get("pdf_path")
            },
            "statistics": stats,
            "active_interviews": interviews,
            "requires_human_decision": requires_human_attention,
            "actionable_alerts": actionable_alerts,
            "agent_briefing": agent_briefing,
        }

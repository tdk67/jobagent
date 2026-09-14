"""Event-loop autonomous agent for JobAgent.

The Strands model-driven agent is the DECISION-MAKER of this loop. When new
emails arrive (timer wake or A2A event push), the agent:

  WAKE   -> PERCEIVE (delta: unseen raw emails + pending approvals + cycle state)
         -> DECIDE  (one Strands LLM call, schema-validated plan)
         -> EXECUTE (keep DB current: fetch new raw emails, classify them into CRM)
         -> RECORD  (agent_cycles row with the agent's own reasoning)

The deterministic engines live INSIDE the tools — the agent chooses when and
whether to invoke them. The loop's job is DB currency (download + classify +
update CRM), NOT report generation — reports are a user command. When no LLM
credentials exist, the loop degrades loudly: it runs a deterministic fallback
but never claims to have reasoned (agent_ok=False, briefing tagged [offline]).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.agent.coordinator import JobAgentCoordinator

log = logging.getLogger(__name__)

THRESHOLD_CONFIDENCE = 0.70  # below this the agent asks a human instead of auto-acting


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventLoopAgent:
    """Runs one wake→perceive→agent-turn→record iteration and the loop around it.

    wake:      poll_seconds interval (timer) or an explicit wake() call (A2A push).
    perceive:  delta = unseen raw emails since the last watermark; pending approvals.
    agent_turn: the Strands agent itself calls the registered tools (ingest_emails,
                get_pipeline_statistics, ask_human_for_approval) during its native
                tool_use loop. The coordinator state (latest_triage) is mutated by
                the tools — NO JSON-plan scripting here.
    record:    agent_cycles row with honesty: when the LLM is unavailable the loop
               runs the deterministic ingest but labels it [offline] and never
               claims the agent reasoned.
    """

    def __init__(
        self,
        coordinator: Optional[JobAgentCoordinator] = None,
        poll_seconds: int = 300,
        watermark_key: str = "event_loop_last_seen",
    ):
        self.coordinator = coordinator or JobAgentCoordinator()
        self.poll_seconds = max(10, int(poll_seconds))
        self.watermark_key = watermark_key
        self.agent = self.coordinator.agent
        self.llm_available = bool(getattr(self.coordinator, "llm_available", False))
        self.last_delta: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------ wake
    def wake(self, reason: str = "timer") -> Dict[str, Any]:
        """Wakes the loop, downloads the most recent emails, and computes the delta.

        This is the 'download new emails' half: fetch_and_cache_emails is idempotent
        (INSERT OR IGNORE on entry_id), so calling it every wake both refreshes the
        mailbox and lets us diff against the watermark.
        """
        try:
            self.coordinator.email_engine.fetch_and_cache_emails(limit=None, start_date=None, end_date=None)
        except Exception as e:
            log.warning("Email fetch failed on wake: %s", e, exc_info=True)

        last_seen = self._load_watermark()
        all_raw = self.coordinator.storage.list_raw_emails()
        new_emails = [e for e in all_raw if not last_seen or e["entry_id"] > last_seen]
        new_emails.sort(key=lambda e: e.get("received_time") or "")
        pending = self.coordinator.storage.list_pending_approvals(status="pending")

        self.last_delta = new_emails
        state = {
            "reason": reason,
            "new_email_count": len(new_emails),
            "pending_approvals": len(pending),
            "new_emails": [
                {
                    "entry_id": e["entry_id"],
                    "sender_name": e.get("sender_name"),
                    "sender_email": e.get("sender_email"),
                    "subject": e.get("subject"),
                    "received_time": e.get("received_time"),
                }
                for e in new_emails
            ],
            "cycle_id": f"evt_{uuid.uuid4().hex[:10]}",
            "timestamp": _now_iso(),
        }
        log.info("wake reason=%s new_emails=%d pending_approvals=%d", reason, len(new_emails), len(pending))
        return state

    # --------------------------------------------------------------- perceive
    def _load_watermark(self) -> Optional[str]:
        try:
            row = self.coordinator.storage.get_setting(self.watermark_key)
            return row if row else None
        except Exception:
            return None

    def _save_watermark(self, entry_id: str) -> None:
        try:
            self.coordinator.storage.set_setting(self.watermark_key, entry_id)
        except Exception as e:
            log.warning("Watermark save failed: %s", e)

    # --------------------------------------------------- agent turn (decide+execute)
    def agent_turn(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Gives the Strands agent the perceived state; it calls the tools itself.

        The loop does NOT script which tools run — the model decides during its
        native tool_use loop. The results land in coordinator.latest_triage and
        latest_reports via the registered tools. When no LLM is available the
        deterministic ingest runs instead, clearly labeled [offline].
        """
        if self.llm_available and self.agent and getattr(self.agent, "model", None):
            mission = (
                "You are JobAgent's autonomous background loop. New emails have arrived. "
                "Keep the local career CRM current by calling the appropriate tools. "
                "Use `ingest_emails` to download and classify the new raw emails into the CRM. "
                "You may call `get_pipeline_statistics` to verify the CRM state, and "
                "`ask_human_for_approval` if a decision needs human review. "
                "Reports are generated on user command — never trigger them here. "
                "Finish with a one-sentence professional briefing of what you did for the candidate.\n\n"
                f"Perceived state: {json.dumps({'reason': state.get('reason'), 'new_email_count': state.get('new_email_count'), 'pending_approvals': state.get('pending_approvals'), 'cycle_id': state.get('cycle_id')}, default=str)}\n"
                f"New emails: {json.dumps(state.get('new_emails', []), default=str)}"
            )
            try:
                res = self.agent(mission)
                msg = getattr(res, "message", {})
                briefing = ""
                if isinstance(msg, dict):
                    content = msg.get("content", [])
                    briefing = " ".join(
                        b.get("text") for b in content if isinstance(b, dict) and "text" in b
                    ).strip()
                agent_ok = True

                # The tools mutated coordinator state during the turn — read what the agent did.
                triage_res = getattr(self.coordinator, "latest_triage", None) or {}
                return {
                    "agent_ok": True,
                    "briefing": briefing or (res.message.text if getattr(res, "message", None) else ""),
                    "triage": triage_res,
                    "reasoning": "agent-driven tool calls",
                    "actions_from_tools": True,
                }
            except Exception as e:
                log.warning("Agent turn failed: %s", e, exc_info=True)
                # Fall through to the honest deterministic fallback.
                return self._offline_ingest(state, agent_error=str(e))

        return self._offline_ingest(state)

    def _offline_ingest(self, state: Dict[str, Any], agent_error: Optional[str] = None) -> Dict[str, Any]:
        """Deterministic ingest when the LLM is unavailable. Loudly labeled — never
        claims the agent reasoned."""
        triage_res: Dict[str, Any] = {}
        if state.get("new_email_count", 0) > 0:
            triage_res = self.coordinator.email_engine.run_triage(
                limit=len(state.get("new_emails", [])),
                start_date=None,
                end_date=None,
            )
            self.coordinator.latest_triage = triage_res
            # Surface interviews as approval requests so the human can react.
            for alert in triage_res.get("actionable_alerts", []):
                self.coordinator.storage.create_pending_approval(
                    question=f"Interview invitation from {alert.get('company')} requires confirm",
                    context=alert.get("subject", ""),
                    urgency="high",
                )
        err_tag = f" [agent-error: {agent_error}]" if agent_error else ""
        return {
            "agent_ok": False,
            "briefing": "[offline] no LLM credentials — deterministic fallback only" + err_tag,
            "triage": triage_res,
            "reasoning": "[offline-fallback]" + (f" processed {state.get('new_email_count', 0)} new email(s)" if triage_res else " nothing new"),
            "actions_from_tools": False,
        }

    def record_cycle(self, state: Dict[str, Any], outcome: Dict[str, Any]) -> None:
        """Persists the agent cycle with an honest status and audit trail."""
        triage_res = outcome.get("triage") or {}
        self.coordinator.storage.record_agent_cycle(
            cycle_id=state.get("cycle_id", "evt_0"),
            status="completed" if outcome.get("agent_ok") else "fallback",
            triage_result=triage_res,
            reports_result=self.coordinator.latest_reports if hasattr(self.coordinator, "latest_reports") else None,
            error=None if outcome.get("agent_ok") else outcome.get("reasoning"),
        )
        new_ids = [e["entry_id"] for e in state.get("new_emails", [])]
        if new_ids:
            self._save_watermark(max(new_ids))

    # ------------------------------------------------------------------ loop
    def run(self, iterations: Optional[int] = None) -> None:
        count = 0
        while iterations is None or count < iterations:
            count += 1
            state = self.wake(reason="timer")
            outcome = self.agent_turn(state)
            self.record_cycle(state, outcome)
            log.info(
                "cycle=%s agent_ok=%s new_emails=%d",
                state["cycle_id"],
                outcome["agent_ok"],
                state.get("new_email_count", 0),
            )
            if iterations is not None:
                return
            time.sleep(self.poll_seconds)
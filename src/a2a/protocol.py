"""Protocol schemas and models for Agent-to-Agent (A2A) communication."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class A2ACapability(BaseModel):
    id: str
    name: str
    description: str
    parameters_schema: Dict[str, Any] = Field(default_factory=dict)
    returns_schema: Dict[str, Any] = Field(default_factory=dict)


class TaskEnvelope(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_agent: str = "hermes"  # e.g. "hermes", "openclaw", "openbot"
    action: str  # e.g. "triage_emails", "archive_job", "generate_compliance_report", "get_status", "query_qa"
    payload: Dict[str, Any] = Field(default_factory=dict)
    callback_url: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TaskResponse(BaseModel):
    task_id: str
    status: str  # "completed", "failed", "requires_human_decision"
    result: Dict[str, Any] = Field(default_factory=dict)
    artifacts: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    completed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class A2AEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str  # "interview_detected", "rejection_logged", "compliance_report_ready", "alert"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: Dict[str, Any] = Field(default_factory=dict)
    priority: str = "normal"  # "low", "normal", "high", "urgent"

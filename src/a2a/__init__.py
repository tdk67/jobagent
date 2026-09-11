"""A2A (Agent-to-Agent) Interface and MCP server package."""
from src.a2a.protocol import TaskEnvelope, TaskResponse, A2ACapability, A2AEvent
from src.a2a.server import create_a2a_app

__all__ = ["TaskEnvelope", "TaskResponse", "A2ACapability", "A2AEvent", "create_a2a_app"]

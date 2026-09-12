"""Service for applications, interviews, statistics, and screening QA memory."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.core.storage import JobAgentStorage

log = logging.getLogger(__name__)


class ApplicationService:
    """Encapsulates business operations for applications, interviews, and QA memory."""

    def __init__(self, storage: JobAgentStorage) -> None:
        self.storage = storage

    def get_statistics(self) -> Dict[str, Any]:
        """Calculates CRM statistics and response metrics."""
        return self.storage.get_statistics()

    def list_interviews(self) -> List[Dict[str, Any]]:
        """Retrieves all scheduled or active interviews."""
        return self.storage.list_interviews()

    def list_applications(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves most recent job applications."""
        return self.storage.list_applications(limit=limit)

    def get_status(self) -> Dict[str, Any]:
        """Aggregates holistic CRM status for A2A and dashboard."""
        return {
            "statistics": self.get_statistics(),
            "interviews": self.list_interviews(),
            "recent_applications": self.list_applications(limit=5),
        }

    def get_qa_answer(self, question: str) -> Optional[str]:
        """Retrieves verified candidate screening question answer."""
        return self.storage.get_qa_answer(question)

    def save_qa_answer(
        self,
        question: str,
        answer: str,
        category: str = "user_taught",
        verified: int = 1,
    ) -> None:
        """Persists or updates candidate answer in QA memory."""
        self.storage.save_qa_answer(
            question_text=question,
            answer=answer,
            category=category,
            verified=verified,
        )

    def list_qa_memory(self) -> List[Dict[str, Any]]:
        """Returns all verified QA entries."""
        return self.storage.list_qa_memory()

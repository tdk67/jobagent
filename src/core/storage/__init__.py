"""JobAgent Storage Package — Modular Single-Responsibility Architecture.

Exposes:
- JobAgentStorage: Unified facade combining all specialized repositories.
- ApplicationRepo: Application CRUD and deduplication.
- EmailRepo: Ingestion and email interaction tracking.
- InterviewRepo: Calendar management and status transitions.
- StatisticsRepo: Parameterized KPI calculations and analytics.
- QaMemoryRepo: Continuous learning and screening QA memory.
- ImportExportRepo: Summary batch import and reporting exports.
- UNKNOWN_ROLE: Statutory AfA placeholder.
- parse_flexible_date: Date utility helper.
"""

from __future__ import annotations

from src.core.storage.base import BaseStorage, UNKNOWN_ROLE, parse_flexible_date
from src.core.storage.application_repo import ApplicationRepo
from src.core.storage.email_repo import EmailRepo
from src.core.storage.interview_repo import InterviewRepo
from src.core.storage.statistics_repo import StatisticsRepo
from src.core.storage.qa_memory_repo import QaMemoryRepo
from src.core.storage.import_export_repo import ImportExportRepo


class JobAgentStorage(
    ApplicationRepo,
    EmailRepo,
    InterviewRepo,
    StatisticsRepo,
    QaMemoryRepo,
    ImportExportRepo,
):
    """Unified JobAgent local SQLite storage facade.
    
    Inherits all specialized single-responsibility repositories while preserving
    a clean, cohesive public interface conforming to all clean-code guidelines (<300 lines per module).
    """

    def __init__(self, db_path: str = "data/jobagent.db"):
        super().__init__(db_path=db_path)


__all__ = [
    "JobAgentStorage",
    "BaseStorage",
    "ApplicationRepo",
    "EmailRepo",
    "InterviewRepo",
    "StatisticsRepo",
    "QaMemoryRepo",
    "ImportExportRepo",
    "UNKNOWN_ROLE",
    "parse_flexible_date",
]

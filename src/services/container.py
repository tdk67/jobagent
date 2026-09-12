"""Dependency Injection container providing shared singleton service instances."""

from __future__ import annotations

from typing import Optional

from src.core.config import AppConfig, load_config
from src.core.profile import CandidateProfile, load_profile
from src.core.storage import JobAgentStorage
from src.services.application_service import ApplicationService
from src.services.archive_service import ArchiveService
from src.services.email_service import EmailService
from src.services.report_service import ReportService


class ServiceContainer:
    """Holds shared instances of all domain services, storage, and configuration."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        storage: Optional[JobAgentStorage] = None,
        profile: Optional[CandidateProfile] = None,
    ) -> None:
        self.config = config or load_config()
        self.storage = storage or JobAgentStorage(self.config.storage.database_path)
        self.profile = profile or load_profile()

        self.applications = ApplicationService(storage=self.storage)
        self.archives = ArchiveService(storage=self.storage, config=self.config)
        self.emails = EmailService(storage=self.storage, config=self.config)
        self.reports = ReportService(
            storage=self.storage,
            config=self.config,
            profile=self.profile,
        )


_global_container: Optional[ServiceContainer] = None


def get_service_container(
    config: Optional[AppConfig] = None,
    storage: Optional[JobAgentStorage] = None,
    profile: Optional[CandidateProfile] = None,
) -> ServiceContainer:
    """Returns or initializes the shared ServiceContainer instance.
    
    If custom instances are provided (e.g. during testing or custom DB paths),
    returns a newly bound ServiceContainer.
    """
    global _global_container
    if config is not None or storage is not None or profile is not None:
        return ServiceContainer(config=config, storage=storage, profile=profile)

    if _global_container is None:
        _global_container = ServiceContainer()
    return _global_container

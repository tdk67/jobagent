"""JobAgent Core Service Layer.

Provides unified business logic decoupling pure API controllers (HTTP REST / SSE / FastMCP)
from underlying storage, tools, and third-party integrations.
"""

from src.services.application_service import ApplicationService
from src.services.archive_service import ArchiveService
from src.services.email_service import EmailService
from src.services.report_service import ReportService
from src.services.container import ServiceContainer, get_service_container

__all__ = [
    "ApplicationService",
    "ArchiveService",
    "EmailService",
    "ReportService",
    "ServiceContainer",
    "get_service_container",
]

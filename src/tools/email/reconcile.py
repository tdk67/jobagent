"""Reconciles unlinked email interactions with applications and enriches location/channel.

Delegates all data access and state transitions to JobAgentStorage repository,
enforcing clean hexagonal architecture and zero-hardcoding principles.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from src.core.storage import JobAgentStorage

log = logging.getLogger(__name__)


def reconcile_database(db_path: str = "data/jobagent.db") -> Dict[str, Any]:
    """Reconciles unlinked email_interactions and enriches applications in SQLite."""
    storage = JobAgentStorage(db_path=db_path)
    return storage.reconcile_unlinked()


if __name__ == "__main__":
    result = reconcile_database()
    print("Reconciliation results:", result)

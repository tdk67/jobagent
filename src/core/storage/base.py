"""Base storage class for JobAgent local SQLite repository.

Adheres to clean-code architecture:
- 100% private local storage (zero cloud PII leakage).
- Atomic schema migrations and transactions.
- Provides connection and initialization lifecycle for specialized repositories.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

from src.core.migrations import run_migrations
from src.utils.date_utils import parse_flexible_date

log = logging.getLogger(__name__)

# Role used when no role can be parsed from the import data. Must NEVER be a
# fabricated real-sounding title: this value ends up in the statutory AfA
# Eigenbemühungsnachweis, where invented data would be a compliance problem.
UNKNOWN_ROLE = "Unbekannt (bitte prüfen)"


class BaseStorage:
    """Manages SQLite database connection and schema lifecycle."""

    def __init__(self, db_path: str = "data/jobagent.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initializes database tables using the versioned migration framework."""
        run_migrations(self.db_path)

"""Database Migration Runner for JobAgent SQLite Repository.

Provides deterministic, versioned schema management:
- Migration scripts stored in external .sql files in migrations/sql/.
- Tracks applied migrations in the schema_migrations table.
- Atomic script execution within transactions.
- Zero embedded DDL in Python source code.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple, Union

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "sql"


class MigrationRunner:
    """Manages discovery and execution of versioned SQL database migrations."""

    def __init__(self, db_path_or_conn: Union[str, Path, sqlite3.Connection], sql_dir: Optional[Path] = None):
        self.sql_dir = Path(sql_dir) if sql_dir else MIGRATIONS_DIR
        if isinstance(db_path_or_conn, (str, Path)):
            self.db_path = Path(db_path_or_conn)
            self._external_conn = None
        else:
            self.db_path = None
            self._external_conn = db_path_or_conn

    def _get_connection(self) -> sqlite3.Connection:
        if self._external_conn is not None:
            return self._external_conn
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(str(self.db_path))

    def init_migration_table(self, conn: sqlite3.Connection) -> None:
        """Ensures the schema_migrations tracking table exists."""
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
        """)
        conn.commit()

    def get_applied_versions(self, conn: sqlite3.Connection) -> List[int]:
        """Returns a list of integer versions already applied."""
        self.init_migration_table(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT version FROM schema_migrations ORDER BY version ASC")
        return [row[0] for row in cursor.fetchall()]

    def discover_migrations(self) -> List[Tuple[int, str, Path]]:
        """Finds all *.sql migration files in the migrations directory sorted by version."""
        if not self.sql_dir.exists():
            log.warning("Migrations directory does not exist: %s", self.sql_dir)
            return []

        migrations: List[Tuple[int, str, Path]] = []
        for file in self.sql_dir.glob("*.sql"):
            match = re.match(r"^(\d+)_(.+)\.sql$", file.name)
            if match:
                version = int(match.group(1))
                name = match.group(2)
                migrations.append((version, name, file))

        migrations.sort(key=lambda m: m[0])
        return migrations

    def run_migrations(self) -> int:
        """Executes any pending migrations in version sequence. Returns count of applied migrations."""
        conn = self._get_connection()
        try:
            self.init_migration_table(conn)
            applied = set(self.get_applied_versions(conn))
            all_migrations = self.discover_migrations()
            newly_applied = 0

            for version, name, sql_file in all_migrations:
                if version not in applied:
                    log.info("Applying database migration %03d: %s (%s)", version, name, sql_file.name)
                    sql_content = sql_file.read_text(encoding="utf-8")
                    cursor = conn.cursor()
                    cursor.executescript(sql_content)
                    cursor.execute(
                        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                        (version, name, datetime.now(timezone.utc).isoformat()),
                    )
                    conn.commit()
                    newly_applied += 1
                    log.info("✓ Successfully applied migration %03d", version)

            return newly_applied
        finally:
            if self._external_conn is None:
                conn.close()


def run_migrations(db_path_or_conn: Union[str, Path, sqlite3.Connection], sql_dir: Optional[Path] = None) -> int:
    """Convenience function to run all pending migrations for a database."""
    runner = MigrationRunner(db_path_or_conn, sql_dir=sql_dir)
    return runner.run_migrations()

"""Tests for JobAgent Database Migration Framework."""

import sqlite3
from pathlib import Path

from src.core.migrations.runner import MigrationRunner, run_migrations


def test_migrations_execution(tmp_path: Path):
    db_file = tmp_path / "test_mig.db"
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()

    # Create dummy migrations
    (sql_dir / "001_first.sql").write_text("CREATE TABLE test_one (id INTEGER PRIMARY KEY, name TEXT);", encoding="utf-8")
    (sql_dir / "002_second.sql").write_text("CREATE TABLE test_two (id INTEGER PRIMARY KEY, val TEXT);", encoding="utf-8")

    runner = MigrationRunner(db_file, sql_dir=sql_dir)
    applied = runner.run_migrations()
    assert applied == 2

    # Verify tables exist
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cursor.fetchall()]
    assert "schema_migrations" in tables
    assert "test_one" in tables
    assert "test_two" in tables

    # Verify schema_migrations rows
    cursor.execute("SELECT version, name FROM schema_migrations ORDER BY version")
    rows = cursor.fetchall()
    assert rows == [(1, "first"), (2, "second")]

    # Running migrations again should apply 0 migrations (idempotent)
    applied_again = runner.run_migrations()
    assert applied_again == 0
    conn.close()


def test_official_schema_migration(tmp_path: Path):
    db_file = tmp_path / "official.db"
    applied = run_migrations(db_file)
    assert applied >= 1

    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]
    assert "applications" in tables
    assert "email_interactions" in tables
    assert "interviews" in tables
    assert "qa_memory" in tables
    assert "schema_migrations" in tables
    conn.close()

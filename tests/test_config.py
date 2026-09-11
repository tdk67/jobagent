"""Tests for configuration and profile management."""

from pathlib import Path
from src.core.config import load_config, AppConfig
from src.core.profile import load_profile, CandidateProfile


def test_load_config_defaults(tmp_path: Path):
    cfg = load_config(
        local_config_path=str(tmp_path / "non_existent.json"),
        example_config_path="config.example.json",
    )
    assert isinstance(cfg, AppConfig)
    assert cfg.agent.name == "JobAgent"
    assert cfg.a2a.port == 8765
    assert cfg.storage.database_path == "data/jobagent.db"


def test_env_overrides_imap_and_a2a_and_db(tmp_path: Path, monkeypatch):
    """F6 VP1: env vars win over file/default config (env > local > example > defaults)."""
    monkeypatch.setenv("IMAP_HOST", "imap.test")
    monkeypatch.setenv("IMAP_PORT", "1993")
    monkeypatch.setenv("IMAP_USE_SSL", "0")
    monkeypatch.setenv("A2A_HOST", "a2a.env")
    monkeypatch.setenv("A2A_PORT", "9999")
    monkeypatch.setenv("JOBAGENT_DB", str(tmp_path / "env.db"))

    cfg = load_config(
        local_config_path=str(tmp_path / "non_existent.json"),
        example_config_path="config.example.json",
    )

    assert cfg.email_ingestion.generic_imap.host == "imap.test"
    assert cfg.email_ingestion.generic_imap.port == 1993
    assert cfg.email_ingestion.generic_imap.use_ssl is False
    assert cfg.a2a.host == "a2a.env"
    assert cfg.a2a.port == 9999
    assert cfg.storage.database_path == str(tmp_path / "env.db")


def test_env_override_bool_true_variants(tmp_path: Path, monkeypatch):
    """F6 VP1: IMAP_USE_SSL accepts 1/true/yes as truthy."""
    for truthy in ("1", "true", "yes", "TRUE"):
        monkeypatch.setenv("IMAP_USE_SSL", truthy)
        cfg = load_config(
            local_config_path=str(tmp_path / "non_existent.json"),
            example_config_path="config.example.json",
        )
        assert cfg.email_ingestion.generic_imap.use_ssl is True, f"{truthy!r} should parse True"


def test_env_unset_file_and_default_values_win(tmp_path: Path, monkeypatch):
    """F6 VP1: without env vars, file/default values win."""
    for var in ("IMAP_HOST", "IMAP_PORT", "IMAP_USE_SSL", "A2A_HOST", "A2A_PORT", "JOBAGENT_DB"):
        monkeypatch.delenv(var, raising=False)

    cfg = load_config(
        local_config_path=str(tmp_path / "non_existent.json"),
        example_config_path="config.example.json",
    )

    assert cfg.email_ingestion.generic_imap.host == "127.0.0.1"
    assert cfg.email_ingestion.generic_imap.port == 1143
    assert cfg.email_ingestion.generic_imap.use_ssl is True
    assert cfg.a2a.host == "127.0.0.1"
    assert cfg.a2a.port == 8765
    assert cfg.storage.database_path == "data/jobagent.db"


def test_load_profile_fallback(tmp_path: Path):
    profile = load_profile(
        local_path=str(tmp_path / "non_existent_profile.json"),
        example_path="profile.example.json",
    )
    assert isinstance(profile, CandidateProfile)
    assert profile.personal.fullName != ""
    assert profile.personal.email != ""

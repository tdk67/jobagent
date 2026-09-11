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


def test_load_profile_fallback(tmp_path: Path):
    profile = load_profile(
        local_path=str(tmp_path / "non_existent_profile.json"),
        example_path="profile.example.json",
    )
    assert isinstance(profile, CandidateProfile)
    assert profile.personal.fullName != ""
    assert profile.personal.email != ""

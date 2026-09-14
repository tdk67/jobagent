"""Configuration loader and schema definitions for JobAgent.

Adheres to clean-code-architecture rules:
- Secrets are loaded from environment variables (.env).
- Operational parameters are loaded from config.local.json (or config.example.json).
- Never hardcode configuration defaults or API secrets inside code.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load private secrets from .env if present
load_dotenv()

log = logging.getLogger(__name__)


class AgentConfig(BaseModel):
    """Agent LLM provider selection.

    All real provider/model values live in config.example.json / config.local.json
    per the project rule 'operational parameters are loaded from config files,
    never hardcoded in code'. The defaults here are intentionally provider-agnostic
    placeholders, never real model identifiers.
    """
    name: str = "JobAgent"
    provider: str = ""
    model: str = ""
    fallback_provider: str = ""
    fallback_model: str = ""
    temperature: float = 0.1



class A2AConfig(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8765
    mcp_enabled: bool = True
    callback_timeout_seconds: int = 30


class StorageConfig(BaseModel):
    database_path: str = "data/jobagent.db"
    archive_dir: str = "data/archives"
    snapshot_dir: str = "data/snapshots"
    qa_memory_path: str = "data/qa_memory.json"


class GmailConfig(BaseModel):
    enabled: bool = True
    method: str = "mcp"  # "mcp", "imap", or "oauth"
    auto_tag_labels: Dict[str, str] = Field(
        default_factory=lambda: {
            "parent": "JobSearch",
            "applications": "JobSearch/Applications",
            "interviews": "JobSearch/Interviews",
            "rejections": "JobSearch/Rejections",
        }
    )


class OutlookDesktopConfig(BaseModel):
    enabled: bool = True
    folder_names: List[str] = Field(default_factory=lambda: ["Bewerbung", "Inbox"])


class GenericImapConfig(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 1143
    use_ssl: bool = True


class EmailIngestionConfig(BaseModel):
    gmail: GmailConfig = Field(default_factory=GmailConfig)
    outlook_desktop: OutlookDesktopConfig = Field(default_factory=OutlookDesktopConfig)
    generic_imap: GenericImapConfig = Field(default_factory=GenericImapConfig)
    llm_fallback: bool = False


class ReportingConfig(BaseModel):
    output_dir: str = "output"
    enable_afa_format: bool = True
    enable_pdf_export: bool = True
    default_views: List[str] = Field(
        default_factory=lambda: ["dashboard", "afa_table", "agency_summary"]
    )


class AppConfig(BaseModel):
    agent: AgentConfig = Field(default_factory=AgentConfig)
    a2a: A2AConfig = Field(default_factory=A2AConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    email_ingestion: EmailIngestionConfig = Field(default_factory=EmailIngestionConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)


def _parse_bool_env(value: Optional[str]) -> Optional[bool]:
    """Parse IMAP_USE_SSL-style env values: '1', 'true', 'yes' (any case) -> True, else False."""
    if value is None or value.strip() == "":
        return None
    return value.strip().lower() in ("1", "true", "yes")


@dataclass
class _EnvOverrides:
    """Optional env-driven overrides applied after config file merge (env > files > defaults)."""
    imap_host: Optional[str] = None
    imap_port: Optional[int] = None
    imap_use_ssl: Optional[bool] = None
    a2a_host: Optional[str] = None
    a2a_port: Optional[int] = None
    database_path: Optional[str] = None


def _collect_env_overrides() -> _EnvOverrides:
    """Read env vars that F6 wires into the config (precedence: env > config files > defaults).

    Invalid int values are logged as warnings and ignored so a bad value cannot
    crash startup silently or mask the file/default config.
    """
    o = _EnvOverrides()
    o.imap_host = os.getenv("IMAP_HOST") or None
    o.imap_use_ssl = _parse_bool_env(os.getenv("IMAP_USE_SSL"))
    o.a2a_host = os.getenv("A2A_HOST") or None
    o.database_path = os.getenv("JOBAGENT_DB") or None

    raw_port = os.getenv("IMAP_PORT")
    if raw_port:
        try:
            o.imap_port = int(raw_port)
        except ValueError:
            log.warning("Ignoring invalid IMAP_PORT env value %r (must be an int)", raw_port)
    raw_a2a_port = os.getenv("A2A_PORT")
    if raw_a2a_port:
        try:
            o.a2a_port = int(raw_a2a_port)
        except ValueError:
            log.warning("Ignoring invalid A2A_PORT env value %r (must be an int)", raw_a2a_port)
    return o


def _apply_env_overrides(cfg: AppConfig, o: _EnvOverrides) -> AppConfig:
    """Apply env overrides onto the merged config (in place, returns cfg for chaining)."""
    if o.imap_host is not None:
        cfg.email_ingestion.generic_imap.host = o.imap_host
    if o.imap_port is not None:
        cfg.email_ingestion.generic_imap.port = o.imap_port
    if o.imap_use_ssl is not None:
        cfg.email_ingestion.generic_imap.use_ssl = o.imap_use_ssl
    if o.a2a_host is not None:
        cfg.a2a.host = o.a2a_host
    if o.a2a_port is not None:
        cfg.a2a.port = o.a2a_port
    if o.database_path is not None:
        cfg.storage.database_path = o.database_path
    return cfg


def _deep_merge(target: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merges source dict into target dict."""
    for key, value in source.items():
        if isinstance(value, dict) and key in target and isinstance(target[key], dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
    return target


def load_config(
    local_config_path: str = "config.local.json",
    example_config_path: str = "config.example.json",
) -> AppConfig:
    """Loads configuration with precedence: config.local.json > config.example.json > defaults."""
    merged_data: Dict[str, Any] = {}

    example_p = Path(example_config_path)
    if example_p.exists():
        try:
            with open(example_p, "r", encoding="utf-8") as f:
                merged_data = json.load(f)
        except Exception as e:
            log.warning("Failed to load example config from %s: %s", example_p, e, exc_info=True)

    local_p = Path(local_config_path)
    if local_p.exists():
        try:
            with open(local_p, "r", encoding="utf-8") as f:
                local_data = json.load(f)
                _deep_merge(merged_data, local_data)
        except Exception as e:
            log.warning("Failed to load local config from %s: %s", local_p, e, exc_info=True)

    # Environment overrides (F6): env > config.local.json > config.example.json > defaults.
    cfg = AppConfig(**merged_data) if merged_data else AppConfig()
    cfg = _apply_env_overrides(cfg, _collect_env_overrides())

    # Ensure required target directories exist
    Path(cfg.storage.archive_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.storage.snapshot_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.reporting.output_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.storage.database_path).parent.mkdir(parents=True, exist_ok=True)
    return cfg

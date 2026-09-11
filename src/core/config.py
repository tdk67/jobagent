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
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load private secrets from .env if present
load_dotenv()

log = logging.getLogger(__name__)


class AgentConfig(BaseModel):
    name: str = "JobAgent"
    provider: str = "gemini"
    model: str = "gemini-3.8-flash"
    fallback_provider: str = "bedrock"
    fallback_model: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
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

    # Ensure required target directories exist
    cfg = AppConfig(**merged_data) if merged_data else AppConfig()
    Path(cfg.storage.archive_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.storage.snapshot_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.reporting.output_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.storage.database_path).parent.mkdir(parents=True, exist_ok=True)
    return cfg

"""Google Gemini model provider and utilities for the AWS Strands Agents SDK."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from strands.models.gemini import GeminiModel

from src.core.config import AppConfig

load_dotenv()

log = logging.getLogger(__name__)


def create_strands_gemini_model(
    config: Optional[AppConfig] = None,
    model_id: Optional[str] = None,
    temperature: Optional[float] = None,
    api_key: Optional[str] = None,
) -> GeminiModel:
    """Creates a fully compliant Strands GeminiModel instance with native streaming and tool execution."""
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY is not set in environment or config.")

    from src.core.config import load_config
    cfg = config or load_config()

    chosen_model = model_id or cfg.agent.model
    chosen_temp = temperature if temperature is not None else cfg.agent.temperature

    return GeminiModel(
        model_id=chosen_model,
        client_args={"api_key": key},
        params={"temperature": chosen_temp},
    )


def call_gemini_semantic_analysis(
    prompt: str,
    model_id: Optional[str] = None,
    temperature: Optional[float] = None,
    config: Optional[AppConfig] = None,
    api_key: Optional[str] = None,
    raise_on_error: bool = False,
) -> str:
    """Synchronous helper for zero-shot email triage and form field semantic reasoning."""
    from google import genai

    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        if raise_on_error:
            raise ValueError("GEMINI_API_KEY is not set in environment (.env).")
        log.debug("GEMINI_API_KEY not set; skipping LLM semantic analysis")
        return ""

    from src.core.config import load_config
    cfg = config or load_config()
    target_model = model_id or cfg.agent.model
    target_temp = temperature if temperature is not None else cfg.agent.temperature

    try:
        client = genai.Client(api_key=key)
        res = client.models.generate_content(
            model=target_model,
            contents=prompt,
            config={"temperature": target_temp},
        )
        return res.text or ""
    except Exception as e:
        log.warning("Gemini semantic analysis call failed (model=%s): %s", target_model, e, exc_info=True)
        if raise_on_error:
            raise
        return ""

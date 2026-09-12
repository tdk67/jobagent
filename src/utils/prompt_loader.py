"""Prompt template loader and caching utility for JobAgent.

Externalizes all agent and tool prompts to templates/prompts/ to ensure
separation of prompt content from application code.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

log = logging.getLogger(__name__)

_PROMPT_CACHE: Dict[str, str] = {}


def load_prompt(name: str, base_dir: Optional[Path] = None) -> str:
    """Loads a prompt template by filename from the templates/prompts directory.
    
    Args:
        name: Name of the prompt file (e.g. 'email_classifier.txt').
        base_dir: Optional base path override for testing.
        
    Returns:
        The prompt template text.
        
    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    if name in _PROMPT_CACHE and base_dir is None:
        return _PROMPT_CACHE[name]

    search_dirs = [
        base_dir if base_dir else Path("templates/prompts"),
        Path(__file__).parent.parent.parent / "templates" / "prompts",
    ]

    for d in search_dirs:
        if d is None:
            continue
        p = d / name
        if p.exists():
            content = p.read_text(encoding="utf-8").strip()
            if base_dir is None:
                _PROMPT_CACHE[name] = content
            return content

    raise FileNotFoundError(f"Prompt template '{name}' not found in search paths: {search_dirs}")


def clear_prompt_cache() -> None:
    """Clears the in-memory prompt cache (useful for testing and hot-reloading)."""
    global _PROMPT_CACHE
    _PROMPT_CACHE.clear()

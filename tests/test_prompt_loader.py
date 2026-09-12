"""Unit tests for the externalized prompt template loader."""

from __future__ import annotations

import pytest
from pathlib import Path

from src.utils.prompt_loader import load_prompt, clear_prompt_cache


def test_load_all_registered_prompts():
    clear_prompt_cache()
    
    prompts = [
        "email_classifier.txt",
        "qa_validator.txt",
        "form_reasoner.txt",
        "coordinator_system.txt",
    ]
    
    for name in prompts:
        content = load_prompt(name)
        assert content is not None
        assert len(content) > 20
        # Verify cached
        assert load_prompt(name) == content


def test_load_prompt_missing_raises():
    clear_prompt_cache()
    with pytest.raises(FileNotFoundError):
        load_prompt("non_existent_prompt_template_file_xyz.txt")

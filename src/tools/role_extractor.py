"""Intelligent job role and title extraction engine.

Re-exports from src.core.role_extractor to maintain backward compatibility
and prevent architecture layering violations.
"""

from src.core.role_extractor import (
    RoleExtractor,
    extract_role_from_context,
)

__all__ = [
    "RoleExtractor",
    "extract_role_from_context",
]

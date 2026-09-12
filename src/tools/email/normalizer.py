"""Entity normalization and noise filtering for companies and job roles.

Re-exports from src.core.normalizer to maintain backward compatibility
and prevent architecture layering violations.
"""

from src.core.normalizer import (
    FUNCTIONAL_SUFFIX_REGEX,
    GENDER_TAGS_REGEX,
    LEGAL_FORM_REGEX,
    NOISE_COMPANY_PATTERNS,
    PLACEHOLDER_ROLES,
    is_noise_company,
    normalize_company_name,
    normalize_role_title,
)

__all__ = [
    "FUNCTIONAL_SUFFIX_REGEX",
    "GENDER_TAGS_REGEX",
    "LEGAL_FORM_REGEX",
    "NOISE_COMPANY_PATTERNS",
    "PLACEHOLDER_ROLES",
    "is_noise_company",
    "normalize_company_name",
    "normalize_role_title",
]

"""Candidate profile loader and schema models.

Adheres to clean-code-architecture rules:
- Candidate PII strictly lives in git-ignored profile.local.json.
- profile.example.json serves as the fallback/template with dummy values.
- Never hardcode candidate names, addresses, or phone numbers in application code.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class DocumentPaths(BaseModel):
    germanCv: Optional[str] = None
    englishCv: Optional[str] = None
    referenceLetter: Optional[str] = None
    coverLetter: Optional[str] = None
    certificatesDir: Optional[str] = None


class PersonalInfo(BaseModel):
    fullName: str = "Candidate Name"
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    middleName: Optional[str] = None
    email: str = "candidate@example.com"
    phone: str = "+49 000 000000"
    phoneCountryCode: str = "+49"
    street: Optional[str] = None
    postalCode: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    countryDe: str = "Deutschland"
    countryEn: str = "Germany"
    address: str = "City, Germany"
    citizenship: str = "EU Citizen (Full Work Authorization)"
    citizenshipDe: Optional[str] = None
    citizenshipEn: Optional[str] = None
    workAuthorizationDe: Optional[str] = None
    workAuthorizationEn: Optional[str] = None
    birthDate: Optional[str] = None
    salaryExpectation: str = "Competitive"
    noticePeriod: str = "Immediately"
    linkedinUrl: Optional[str] = None
    githubUrl: Optional[str] = None
    summaryDe: Optional[str] = None
    summaryEn: Optional[str] = None


class TechnicalSkills(BaseModel):
    core: List[str] = Field(default_factory=list)
    yearsExperience: Dict[str, int] = Field(default_factory=dict)


class Preferences(BaseModel):
    workModel: str = "Hybrid or Remote"
    locations: List[str] = Field(default_factory=list)
    targetRoles: List[str] = Field(default_factory=list)


class CandidateProfile(BaseModel):
    personal: PersonalInfo = Field(default_factory=PersonalInfo)
    technical_skills: TechnicalSkills = Field(default_factory=TechnicalSkills)
    preferences: Preferences = Field(default_factory=Preferences)
    documents: DocumentPaths = Field(default_factory=DocumentPaths)
    languages: Dict[str, str] = Field(default_factory=dict)
    common_answers: Dict[str, str] = Field(default_factory=dict)
    work_experience: List[Dict[str, Any]] = Field(default_factory=list)
    education: List[Dict[str, Any]] = Field(default_factory=list)


def load_profile(
    local_path: str = "profile.local.json",
    example_path: str = "profile.example.json",
) -> CandidateProfile:
    """Loads candidate profile from profile.local.json with fallback to profile.example.json."""
    data: Dict[str, Any] = {}

    local_p = Path(local_path)
    if local_p.exists():
        try:
            with open(local_p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            log.warning("Failed to load local candidate profile from %s: %s", local_p, e, exc_info=True)

    if not data:
        example_p = Path(example_path)
        if example_p.exists():
            try:
                with open(example_p, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                log.warning("Failed to load example candidate profile from %s: %s", example_p, e, exc_info=True)

    if not data:
        return CandidateProfile()

    # Normalization from migrated schema
    personal_dict = data.get("personal", {})
    job_search = data.get("jobSearch", {})
    if job_search:
        if not personal_dict.get("salaryExpectation"):
            personal_dict["salaryExpectation"] = job_search.get("salaryFormatted") or job_search.get("salaryExpectation") or "Competitive"
        if not personal_dict.get("noticePeriod"):
            personal_dict["noticePeriod"] = job_search.get("noticePeriodDe") or job_search.get("noticePeriodEn") or "Immediately"
        if not personal_dict.get("workAuthorizationDe"):
            personal_dict["workAuthorizationDe"] = job_search.get("workAuthorizationDe")
        if not personal_dict.get("workAuthorizationEn"):
            personal_dict["workAuthorizationEn"] = job_search.get("workAuthorizationEn")

    if personal_dict.get("linkedin") and not personal_dict.get("linkedinUrl"):
        personal_dict["linkedinUrl"] = personal_dict["linkedin"]
    if personal_dict.get("github") and not personal_dict.get("githubUrl"):
        personal_dict["githubUrl"] = personal_dict["github"]
    if not personal_dict.get("address") and (personal_dict.get("street") or personal_dict.get("city")):
        parts = [p for p in [personal_dict.get("street"), f"{personal_dict.get('postalCode', '')} {personal_dict.get('city', '')}".strip(), personal_dict.get("countryDe") or personal_dict.get("countryEn")] if p]
        personal_dict["address"] = ", ".join(parts)

    data["personal"] = personal_dict

    # Map skills if top-level skills dict exists
    if "skills" in data and "technical_skills" not in data:
        data["technical_skills"] = {
            "core": list(data["skills"].keys()),
            "yearsExperience": data["skills"],
        }

    # Map preferences from jobSearch
    pref_dict = data.get("preferences", {})
    if job_search and "preferredLocations" in job_search and not pref_dict.get("locations"):
        pref_dict["locations"] = job_search["preferredLocations"]
    data["preferences"] = pref_dict

    # Map languages
    if "languages" in data and "languages" not in data:
        data["languages"] = data["languages"]

    # Consolidate QA memory strictly from profile (single source of truth)
    common_answers = data.get("common_answers", {})
    if "qaAnswers" in data:
        common_answers.update(data["qaAnswers"])
    elif "qa_answers" in data:
        common_answers.update(data["qa_answers"])

    data["common_answers"] = common_answers

    if "workExperience" in data and "work_experience" not in data:
        data["work_experience"] = data["workExperience"]

    if "education" in data and "education" not in data:
        data["education"] = data["education"]

    return CandidateProfile(**data)

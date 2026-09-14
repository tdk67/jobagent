"""Continuous learning & verified QA memory repository for JobAgent.

Handles:
- Persistent question-answering memory for job applications.
- Canonical key normalization and semantic token-overlap matching.
- Provenance and verification status tracking (user_verified vs llm_suggested).
- Lazy seeding from candidate profile common answers and skill years.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.core.storage.base import BaseStorage

log = logging.getLogger(__name__)


class QaMemoryRepo(BaseStorage):
    """Repository handling persistent screening questions, answers, and verification."""

    @staticmethod
    def normalize_question(text: str) -> str:
        """Normalizes question text for consistent canonical lookup."""
        if not text:
            return ""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def save_qa_answer(
        self,
        question_text: Optional[str] = None,
        answer: str = "",
        category: str = "general",
        verified: int = 1,
        provenance: str = "user_verified",
        question: Optional[str] = None,
    ) -> None:
        """Saves or updates a question-answer pair into persistent QA memory with provenance tracking."""
        raw_q = question_text or question or ""
        norm_key = self.normalize_question(raw_q)
        if not norm_key or len(norm_key) < 3:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO qa_memory (question_key, question_text, answer, category, verified, provenance, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(question_key) DO UPDATE SET
                    question_text = excluded.question_text,
                    answer = excluded.answer,
                    category = excluded.category,
                    verified = excluded.verified,
                    provenance = excluded.provenance,
                    updated_at = excluded.updated_at
                """,
                (norm_key, raw_q.strip(), str(answer).strip(), category, verified, provenance, now),
            )
            conn.commit()

    def get_qa_answer(self, question_text: str, verified_only: bool = True) -> Optional[str]:
        """Looks up a question in persistent QA memory by exact canonical key or significant phrase/token overlap.
        
        Args:
            question_text: Natural language question text.
            verified_only: When True (default), only return user-verified answers (verified=1).
                           Prevents unverified LLM suggestions from being treated as authoritative.
        """
        norm_key = self.normalize_question(question_text)
        # Protect against garbage 1-2 char searches (e.g. 'a', 'e', 'sal')
        if not norm_key or len(norm_key) < 3:
            return None

        where_cond = "WHERE verified = 1" if verified_only else ""
        where_key_cond = "WHERE question_key = ?" + (" AND verified = 1" if verified_only else "")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. Exact canonical match
            cursor.execute(
                f"SELECT answer FROM qa_memory {where_key_cond}",
                (norm_key,),
            )
            row = cursor.fetchone()
            if row:
                return row["answer"]

            # 2. Phrase and token-overlap match (eliminates accidental substring hits like 'a' in 'salary')
            cursor.execute(f"SELECT question_key, answer FROM qa_memory {where_cond}")
            all_entries = cursor.fetchall()

            query_tokens = set(norm_key.split())
            stop_words = {
                "in", "for", "a", "an", "the", "der", "die", "das", "und", "oder", "ist", "sind",
                "do", "you", "your", "have", "please", "bitte", "geben", "sie", "an", "ihre",
                "deine", "mit", "what", "which", "where", "how", "many", "is", "are", "my", "of",
            }
            significant_query = {t for t in query_tokens if len(t) >= 3 and t not in stop_words}
            padded_query = f" {norm_key} "

            best_match = None
            best_score = 0.0

            for r in all_entries:
                key = r["question_key"]
                if not key or len(key) < 3:
                    continue

                padded_key = f" {key} "

                # Whole phrase match with word boundaries in either direction
                # (e.g. "expected salary" inside "what is your expected salary")
                # Enforces that query contains at least one significant non-stop word
                if (padded_query in padded_key or padded_key in padded_query) and significant_query:
                    return r["answer"]

                key_tokens = set(key.split())
                significant_key = {t for t in key_tokens if len(t) >= 3 and t not in stop_words}
                if not significant_key or not significant_query:
                    continue

                overlap = len(significant_query & significant_key)
                # Score against smaller set to handle concise queries matching longer questions
                min_len = min(len(significant_key), len(significant_query))
                score = overlap / min_len
                if score >= 0.7 and score > best_score:
                    best_score = score
                    best_match = r["answer"]

            if best_match:
                return best_match

        return None

    def list_qa_memory(self) -> List[Dict[str, Any]]:
        """Returns all stored QA memory entries."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM qa_memory ORDER BY updated_at DESC")
            return [dict(r) for r in cursor.fetchall()]

    def seed_qa_from_profile(self, profile: Any) -> None:
        """Seeds QA memory from CandidateProfile common_answers and skills."""
        if not profile:
            return

        common_answers = getattr(profile, "common_answers", {}) or {}
        for q, a in common_answers.items():
            self.save_qa_answer(q, str(a), category="profile_common")

        # Technical skills years
        tech = getattr(profile, "technical_skills", None)
        years = getattr(tech, "yearsExperience", {}) if tech else {}
        SKILL_TEMPLATES = [
            ("How many years of experience do you have with {skill}?", "{yr} years"),
            ("Wie viele Jahre Erfahrung haben Sie mit {skill}?", "{yr} Jahre"),
        ]
        for skill, yr in years.items():
            for q_tmpl, a_tmpl in SKILL_TEMPLATES:
                self.save_qa_answer(
                    q_tmpl.format(skill=skill),
                    a_tmpl.format(yr=yr),
                    category="skill_experience",
                )

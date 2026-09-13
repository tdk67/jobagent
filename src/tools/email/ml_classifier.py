"""Offline ML-based email classifier using a trained scikit-learn pipeline.

Serves as Tier 2 in the classification stack:
  Tier 1: Rule-based (fast, high-precision for clear-cut cases)
  Tier 2: ML (offline, no API quota, handles ambiguous cases)
  Tier 3: LLM (slow, expensive, only for very low ML confidence)

The model is trained by scripts/train_ml_classifier.py on historical emails.
If the model is not found, predict() returns None (graceful degradation).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import Optional

log = logging.getLogger(__name__)

# Default model directory relative to project root
_DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[3] / "models" / "email_classifier"

# Minimum probability to trust the ML prediction (with 6 classes, random chance is 17%)
_DEFAULT_MIN_CONFIDENCE = 0.40

# Map ML class names → classifier.py category names (they should match, but just in case)
_LABEL_MAP = {
    "rejection": "rejection",
    "interview_invitation": "interview_invitation",
    "application_confirmation": "application_confirmation",
    "verification": "verification",
    "follow_up": "follow_up",
    "noise": "noise",
}


def _clean_body_text(body: str) -> str:
    if not body:
        return ""
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", body)
    # Strip zero-width spaces, invisible unicode padding, and excessive whitespace
    text = re.sub(r"[\u034f\u200b-\u200f\ufeff\s]+", " ", text).strip()
    return text


def _build_feature_text(subject: str, body: str, sender: str = "") -> str:
    """Mirror of train script's build_feature_text — must stay in sync."""
    subj_boosted = f"{subject} {subject} {subject}"
    cleaned = _clean_body_text(body)
    body_truncated = cleaned[:1000] if cleaned else ""
    domain = ""
    if sender and "@" in sender:
        domain = sender.split("@")[-1].split(".")[0]
    return f"{subj_boosted} {domain} {body_truncated}".strip()



class MLEmailClassifier:
    """Thin wrapper around a trained sklearn email classification pipeline.

    Usage:
        ml = MLEmailClassifier()
        result = ml.predict(subject, body, sender_email)
        if result:
            print(result.category, result.confidence)
    """

    _instance: Optional["MLEmailClassifier"] = None  # singleton cache

    def __init__(self, model_dir: Optional[Path] = None, min_confidence: float = _DEFAULT_MIN_CONFIDENCE):
        self._model_dir = model_dir or _DEFAULT_MODEL_DIR
        self._min_confidence = min_confidence
        self._pipeline = None
        self._label_encoder = None
        self._metadata: dict = {}
        self._loaded = False

    @classmethod
    def get_instance(cls, model_dir: Optional[Path] = None) -> "MLEmailClassifier":
        """Return a shared (singleton) instance — avoids reloading model on each call."""
        if cls._instance is None:
            cls._instance = cls(model_dir=model_dir)
        return cls._instance

    def load(self) -> bool:
        """Load model artifacts from disk. Returns True if successful."""
        if self._loaded:
            return self._pipeline is not None

        pipeline_path = self._model_dir / "pipeline.pkl"
        encoder_path = self._model_dir / "label_encoder.pkl"
        metadata_path = self._model_dir / "metadata.json"

        if not pipeline_path.exists():
            log.debug("ML model not found at %s — skipping ML tier", pipeline_path)
            self._loaded = True  # mark as attempted so we don't retry every call
            return False

        try:
            import joblib
            self._pipeline = joblib.load(str(pipeline_path))
            self._label_encoder = joblib.load(str(encoder_path))
            if metadata_path.exists():
                with open(metadata_path, encoding="utf-8") as f:
                    self._metadata = json.load(f)
            self._loaded = True
            acc = self._metadata.get("accuracy", "?")
            trained = self._metadata.get("trained_at", "unknown")
            log.info("ML classifier loaded (accuracy=%.1f%%, trained=%s)",
                     float(acc) * 100 if isinstance(acc, (int, float)) else 0, trained)
            return True
        except Exception as e:
            log.warning("Failed to load ML model: %s", e)
            self._loaded = True
            return False

    def predict(
        self,
        subject: str,
        body: str,
        sender_email: str = "",
    ):
        """Classify an email. Returns ClassificationResult or None if unavailable/low-confidence.

        Returns:
            ClassificationResult if confident, None otherwise (triggers next tier).
        """
        # Lazy load on first call
        if not self._loaded:
            self.load()

        if self._pipeline is None:
            return None

        try:
            feature = _build_feature_text(subject, body, sender_email)
            proba = self._pipeline.predict_proba([feature])[0]
            pred_idx = proba.argmax()
            confidence = float(proba[pred_idx])
            raw_label = str(self._label_encoder.inverse_transform([pred_idx])[0])
            category = _LABEL_MAP.get(raw_label, "noise")

            sorted_proba = sorted(proba, reverse=True)
            margin = float(sorted_proba[0] - (sorted_proba[1] if len(sorted_proba) > 1 else 0.0))
            is_confident = (confidence >= self._min_confidence) or (confidence >= 0.35 and margin >= 0.10)


            if not is_confident:
                log.debug("ML confidence %.0f%% (margin %.0f%%) below threshold for '%s' — deferring to LLM",
                          confidence * 100, margin * 100, subject[:60])
                return None

            # Build human-readable reasoning from top TF-IDF features
            reasoning = self._build_reasoning(feature, pred_idx, category, confidence)

            from src.tools.email.classifier import ClassificationResult
            return ClassificationResult(
                category=category,
                confidence=confidence,
                explanation=reasoning,
                intent=raw_label,
                reasoning=reasoning,
            )

        except Exception as e:
            log.warning("ML prediction error: %s", e)
            return None

    def _build_reasoning(self, feature_text: str, pred_idx: int, category: str, confidence: float) -> str:
        """Extract top contributing TF-IDF terms for human-readable reasoning."""
        try:
            tfidf = self._pipeline.named_steps["tfidf"]
            clf = self._pipeline.named_steps["clf"]
            feature_vec = tfidf.transform([feature_text])
            coef_row = clf.coef_[pred_idx]
            # Element-wise weight × feature value
            scores = feature_vec.multiply(coef_row)
            top_indices = scores.toarray()[0].argsort()[-6:][::-1]
            vocab_inv = {v: k for k, v in tfidf.vocabulary_.items()}
            top_terms = [vocab_inv[i] for i in top_indices if i in vocab_inv]
            if top_terms:
                return (
                    f"ML classifier ({confidence:.0%} confidence): "
                    f"key signals -> {', '.join(repr(t) for t in top_terms[:4])}"
                )
        except Exception:
            pass
        return f"ML classifier ({confidence:.0%} confidence) -> {category}"

    def is_available(self) -> bool:
        """True if the model is loaded and ready."""
        if not self._loaded:
            self.load()
        return self._pipeline is not None

    def get_metadata(self) -> dict:
        """Return model metadata (accuracy, training date, etc.)."""
        if not self._loaded:
            self.load()
        return self._metadata.copy()

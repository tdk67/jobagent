"""Train the offline ML email classifier.

Loads the labeled CSV produced by prepare_ml_dataset.py, splits 60/40 for
train/test (chronologically stratified when dates are available), trains a
TF-IDF + LogisticRegression scikit-learn pipeline, evaluates on the test set,
and serializes the model to models/email_classifier/.

Usage:
    python scripts/train_ml_classifier.py [--input PATH] [--model-dir DIR]
"""

import argparse
import json
import logging
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

DEFAULT_INPUT = ROOT / "data" / "ml_training" / "labeled_emails.csv"
DEFAULT_MODEL_DIR = ROOT / "models" / "email_classifier"

# Labels the model will learn — mirrors classifier.py categories
TARGET_LABELS = [
    "rejection",
    "interview_invitation",
    "application_confirmation",
    "verification",
    "follow_up",
    "noise",
]


def _clean_body_text(body: str) -> str:
    if not body:
        return ""
    text = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"[\u034f\u200b-\u200f\ufeff\s]+", " ", text).strip()
    return text


def build_feature_text(subject: str, body: str, sender: str = "") -> str:
    """Combine fields into a single feature string for TF-IDF.
    Subject is repeated 3x to give it higher weight.
    """
    subj_boosted = f"{subject} {subject} {subject}"
    cleaned = _clean_body_text(body)
    body_truncated = cleaned[:1000] if cleaned else ""
    domain = ""
    if sender and "@" in sender:
        domain = sender.split("@")[-1].split(".")[0]
    return f"{subj_boosted} {domain} {body_truncated}".strip()



def load_dataset(csv_path: Path):
    """Load labeled CSV and return (texts, labels)."""
    import csv
    texts, labels = [], []
    skipped = 0
    valid_labels = set(TARGET_LABELS)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            label = row.get("label", "").strip()
            if label not in valid_labels:
                skipped += 1
                continue
            subject = row.get("subject", "") or ""
            body = row.get("body", "") or ""
            sender = row.get("sender", "") or ""
            feature = build_feature_text(subject, body, sender)
            if not feature.strip():
                skipped += 1
                continue
            texts.append(feature)
            labels.append(label)

    log.info("Loaded %d samples (%d skipped)", len(texts), skipped)
    return texts, labels


def train_and_evaluate(texts, labels, model_dir: Path):
    """Train the sklearn pipeline and evaluate on a 40% held-out test set."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.model_selection import StratifiedShuffleSplit
    from sklearn.metrics import classification_report, confusion_matrix
    from sklearn.preprocessing import LabelEncoder
    import joblib
    import numpy as np

    le = LabelEncoder()
    y = le.fit_transform(labels)

    # 60/40 stratified split to preserve label ratios
    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.40, random_state=42)
    train_idx, test_idx = next(sss.split(texts, y))

    X_train = [texts[i] for i in train_idx]
    X_test = [texts[i] for i in test_idx]
    y_train = y[train_idx]
    y_test = y[test_idx]

    log.info("Train size: %d  |  Test size: %d", len(X_train), len(X_test))

    # Build sklearn Pipeline
    pipeline = Pipeline([
        (
            "tfidf",
            TfidfVectorizer(
                analyzer="word",
                ngram_range=(1, 3),          # unigrams, bigrams, trigrams
                max_features=30_000,
                sublinear_tf=True,           # log normalization
                min_df=2,                    # ignore very rare terms
                strip_accents="unicode",
                lowercase=True,
            ),
        ),
        (
            "clf",
            LogisticRegression(
                max_iter=1000,
                class_weight="balanced",    # compensate for class imbalance
                solver="lbfgs",
                C=1.0,
            ),
        ),
    ])

    log.info("Training TF-IDF + LogisticRegression pipeline...")
    pipeline.fit(X_train, y_train)

    # Evaluate on held-out test set
    y_pred = pipeline.predict(X_test)
    y_proba = pipeline.predict_proba(X_test)

    log.info("\n--- Classification Report (40%% test set) ---")
    report_str = classification_report(
        y_test, y_pred,
        target_names=le.classes_,
        digits=3,
        zero_division=0,
    )
    print(report_str)

    log.info("--- Confusion Matrix ---")
    cm = confusion_matrix(y_test, y_pred)
    print("Labels:", list(le.classes_))
    print(cm)

    # Overall accuracy
    accuracy = (y_pred == y_test).mean()
    log.info("Overall accuracy: %.1f%%", accuracy * 100)

    # Per-class breakdown
    label_summary = {}
    from sklearn.metrics import precision_recall_fscore_support
    prec, rec, f1, support = precision_recall_fscore_support(
        y_test, y_pred, labels=range(len(le.classes_)), zero_division=0
    )
    for i, cls in enumerate(le.classes_):
        label_summary[cls] = {
            "precision": round(float(prec[i]), 3),
            "recall": round(float(rec[i]), 3),
            "f1": round(float(f1[i]), 3),
            "support": int(support[i]),
        }

    # --- Save model artifacts ---
    model_dir.mkdir(parents=True, exist_ok=True)

    pipeline_path = model_dir / "pipeline.pkl"
    encoder_path = model_dir / "label_encoder.pkl"
    metadata_path = model_dir / "metadata.json"

    joblib.dump(pipeline, pipeline_path)
    joblib.dump(le, encoder_path)

    import datetime
    metadata = {
        "trained_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "train_size": len(X_train),
        "test_size": len(X_test),
        "accuracy": round(float(accuracy), 4),
        "classes": list(le.classes_),
        "label_summary": label_summary,
        "vectorizer": {
            "ngram_range": [1, 3],
            "max_features": 30000,
        },
    }
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    log.info("Model saved to: %s", model_dir)
    log.info("  pipeline.pkl:     %s", pipeline_path)
    log.info("  label_encoder.pkl: %s", encoder_path)
    log.info("  metadata.json:    %s", metadata_path)

    return pipeline, le, accuracy, label_summary


def main():
    parser = argparse.ArgumentParser(description="Train ML email classifier")
    parser.add_argument(
        "--input", default=str(DEFAULT_INPUT),
        help="Path to labeled_emails.csv from prepare_ml_dataset.py"
    )
    parser.add_argument(
        "--model-dir", default=str(DEFAULT_MODEL_DIR),
        help="Directory to save trained model artifacts"
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    model_dir = Path(args.model_dir)

    if not input_path.exists():
        log.error("Input dataset not found: %s", input_path)
        log.error("Run 'python scripts/prepare_ml_dataset.py' first.")
        sys.exit(1)

    texts, labels = load_dataset(input_path)
    if len(texts) < 50:
        log.error("Too few samples (%d) to train meaningfully.", len(texts))
        sys.exit(1)

    from collections import Counter
    label_counts = Counter(labels)
    log.info("Label distribution: %s", dict(label_counts))

    pipeline, le, accuracy, label_summary = train_and_evaluate(texts, labels, model_dir)

    # Quick smoke test
    test_cases = [
        ("Rejection test", "Leider müssen wir Ihnen mitteilen, dass wir uns für andere Kandidaten entschieden haben.", "hr@company.de"),
        ("Interview test", "Einladung zum Telefoninterview für die Position Java Developer", "recruiter@company.de"),
        ("Confirmation test", "Vielen Dank für Ihre Bewerbung - Eingangsbestätigung", "noreply@personio.de"),
    ]
    log.info("\n--- Smoke Test ---")
    for subject, body, sender in test_cases:
        feature = build_feature_text(subject, body, sender)
        pred = pipeline.predict([feature])[0]
        proba = pipeline.predict_proba([feature])[0]
        predicted_label = le.inverse_transform([pred])[0]
        confidence = max(proba)
        log.info("  Input: '%s'", subject[:60])
        log.info("  -> %s (%.0f%% confidence)", predicted_label, confidence * 100)
        log.info("")

    print(f"\n[OK] Training complete. Model saved to {model_dir}")
    print(f"   Overall accuracy: {accuracy * 100:.1f}%")
    rej = label_summary.get("rejection", {})
    print(f"   Rejection F1: {rej.get('f1', 0):.3f} (target >= 0.70)")


if __name__ == "__main__":
    main()

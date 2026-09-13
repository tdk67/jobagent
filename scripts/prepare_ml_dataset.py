"""Prepare labeled training dataset for the ML email classifier.

Loads historical job-search emails from the external dataset directory,
auto-labels them with the existing rule-based classifier, and merges in
any confirmed labels already stored in the live jobagent SQLite database.
Exports a clean CSV to data/ml_training/labeled_emails.csv.

Usage:
    python scripts/prepare_ml_dataset.py [--dataset-dir PATH] [--output PATH]
"""

import argparse
import logging
import re
import sqlite3
import sys
from pathlib import Path
from collections import Counter

# ---------------------------------------------------------------------------
# Make sure the project root is on sys.path
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

DEFAULT_DATASET_DIR = Path("C:/Data/work/jobSearch")
DEFAULT_OUTPUT = ROOT / "data" / "ml_training" / "labeled_emails.csv"
DB_PATH = ROOT / "data" / "jobagent.db"

# ---------------------------------------------------------------------------
# Label constants (must match classifier.py categories)
# ---------------------------------------------------------------------------
LABEL_REJECTION = "rejection"
LABEL_INTERVIEW = "interview_invitation"
LABEL_CONFIRMATION = "application_confirmation"
LABEL_VERIFICATION = "verification"
LABEL_FOLLOW_UP = "follow_up"
LABEL_NOISE = "noise"

ALL_LABELS = {
    LABEL_REJECTION, LABEL_INTERVIEW, LABEL_CONFIRMATION,
    LABEL_VERIFICATION, LABEL_FOLLOW_UP, LABEL_NOISE,
}


def _clean_body(raw: str) -> str:
    """Strip Outlook RTF artefacts and collapse whitespace."""
    if not isinstance(raw, str):
        return ""
    text = re.sub(r"_x[0-9A-Fa-f]{4}_", " ", raw)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def rule_based_label(subject: str, body: str) -> str:
    """Conservative rule-based labeler that only fires on strong, unambiguous signals."""
    text = f"{subject} {body}".lower()

    interview_strong = [
        r"einladung zum vorstellungsgespr",
        r"einladung zum telefoninterview",
        r"telefoninterview",
        r"invitation to interview",
        r"interview invitation",
        r"schedule an interview",
        r"einladung zum video",
        r"\bpre-call\b",
        r"\bprecall\b",
        r"unser gespr.ch zur stelle",
    ]
    for pat in interview_strong:
        if re.search(pat, text, re.IGNORECASE):
            return LABEL_INTERVIEW

    rejection_strong = [
        r"leider m[uü]ssen wir ihnen mitteilen",
        r"leider k[oö]nnen wir(?! keine)",
        r"leider nicht ber[uü]cksichtigen",
        r"nicht im weiteren auswahlverfahren",
        r"nicht weiter ber[uü]cksichtigen",
        r"haben uns f[uü]r andere",
        r"haben uns letztlich f[uü]r",
        r"entschieden, andere bewerber",
        r"\babsage\b",
        r"regret to inform you",
        r"not moving forward",
        r"decided to move forward with other",
        r"unable to offer you",
        r"will not be moving forward",
        r"not selected for (?:this|the) (?:role|position)",
    ]
    for pat in rejection_strong:
        if re.search(pat, text, re.IGNORECASE):
            return LABEL_REJECTION

    confirmation_pats = [
        r"automatisierte eingangsbes",
        r"eingangsbes",
        r"vielen dank f[uü]r ihre bewerbung",
        r"haben ihre bewerbung erhalten",
        r"bewerbung erfolgreich eingegangen",
        r"thank you for applying",
        r"thank you for your application",
        r"we have received your application",
        r"application received",
        r"application submitted",
    ]
    for pat in confirmation_pats:
        if re.search(pat, text, re.IGNORECASE):
            return LABEL_CONFIRMATION

    verification_pats = [
        r"one-time password",
        r"verification code",
        r"verify your email",
        r"best[aä]tigungscode",
        r"activate your account",
        r"e-mail-adresse best[aä]tigen",
        r"passcode is",
    ]
    for pat in verification_pats:
        if re.search(pat, text, re.IGNORECASE):
            return LABEL_VERIFICATION

    job_context = [
        "bewerbung", "stelle", "position", "lebenslauf", "candidate",
        "application", "resume", " cv ", "job application",
    ]
    if any(k in text for k in job_context):
        return LABEL_FOLLOW_UP

    return LABEL_NOISE


def load_excel_emails(path: Path, subject_col: str, body_col: str,
                      sender_col: str = "Sender") -> list:
    """Load an Excel file and return a list of email dicts."""
    try:
        import pandas as pd
        df = pd.read_excel(str(path))
    except Exception as e:
        log.warning("Could not read %s: %s", path, e)
        return []

    records = []
    for _, row in df.iterrows():
        subject = str(row.get(subject_col, "") or "")
        body = _clean_body(str(row.get(body_col, "") or ""))
        sender = str(row.get(sender_col, "") or "")
        records.append({
            "sender": sender,
            "subject": subject,
            "body": body,
            "source": path.stem,
        })
    log.info("Loaded %d emails from %s", len(records), path.name)
    return records


def load_db_emails(db_path: Path) -> list:
    """Load classified emails from the live jobagent SQLite database."""
    if not db_path.exists():
        log.warning("DB not found: %s", db_path)
        return []

    intent_map = {
        "rejection": LABEL_REJECTION,
        "interview": LABEL_INTERVIEW,
        "interview_invitation": LABEL_INTERVIEW,
        "acknowledgement": LABEL_CONFIRMATION,
        "application_confirmation": LABEL_CONFIRMATION,
        "job_application": LABEL_CONFIRMATION,
        "email_verification": LABEL_VERIFICATION,
        "verification": LABEL_VERIFICATION,
        "info_request": LABEL_FOLLOW_UP,
        "follow_up": LABEL_FOLLOW_UP,
    }

    records = []
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            """
            SELECT ei.subject, COALESCE(re.body, ei.preview, ''), ei.sender_email, ei.intent, ei.category
            FROM email_interactions ei
            LEFT JOIN raw_emails re ON ei.entry_id = re.entry_id
            WHERE (ei.intent IS NOT NULL AND ei.intent != '' AND ei.intent NOT IN ('other', 'unknown'))
               OR (ei.category IS NOT NULL AND ei.category != '' AND ei.category NOT IN ('other', 'unknown'))
            """
        )
        for row in cursor.fetchall():
            subject, body, sender, intent, category = row
            label = intent_map.get(intent) or intent_map.get(category)
            if label and label in ALL_LABELS:
                records.append({
                    "sender": sender or "",
                    "subject": subject or "",
                    "body": _clean_body(body or ""),
                    "label": label,
                    "confidence": 1.0,
                    "source": "jobagent_db",
                })
        conn.close()
        log.info("Loaded %d verified labels from DB", len(records))
    except Exception as e:
        log.warning("DB load error: %s", e)

    return records


def main():
    parser = argparse.ArgumentParser(description="Prepare ML training dataset")
    parser.add_argument(
        "--dataset-dir", default=str(DEFAULT_DATASET_DIR),
        help="Directory containing historical Excel files"
    )
    parser.add_argument(
        "--output", default=str(DEFAULT_OUTPUT),
        help="Output CSV path"
    )
    args = parser.parse_args()

    dataset_dir = Path(args.dataset_dir)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    all_records = []

    # 1. High-quality confirmed labels from live DB
    db_records = load_db_emails(DB_PATH)
    all_records.extend(db_records)

    # 2. Historical Excel datasets
    excel_sources = [
        (dataset_dir / "BewerbungEmails_02.xlsx", "Subject", "Body Text"),
        (dataset_dir / "InboxEmailsJobRelated_Cleaned_Updated.xlsx", "Subject", "Body Preview"),
        (dataset_dir / "InboxEmails_Cleaned.xlsx", "Subject", "Body Preview"),
    ]

    for (xlsx_path, subj_col, body_col) in excel_sources:
        if not xlsx_path.exists():
            log.warning("Skipping missing file: %s", xlsx_path)
            continue
        emails = load_excel_emails(xlsx_path, subj_col, body_col)
        for rec in emails:
            rec["label"] = rule_based_label(rec["subject"], rec["body"])
            rec["confidence"] = 0.85
        all_records.extend(emails)

    if not all_records:
        log.error("No email records loaded. Check dataset directory.")
        sys.exit(1)

    # 3. Deduplicate by (subject, first 200 chars of body)
    seen = set()
    deduped = []
    for rec in all_records:
        key = (rec["subject"].strip().lower(), rec["body"][:200].strip().lower())
        if key not in seen:
            seen.add(key)
            deduped.append(rec)

    log.info("Total records after dedup: %d (removed %d duplicates)",
             len(deduped), len(all_records) - len(deduped))

    label_counts = Counter(r["label"] for r in deduped)
    log.info("Label distribution:")
    for label, count in sorted(label_counts.items(), key=lambda x: -x[1]):
        log.info("  %-30s %4d", label, count)

    # 4. Export to CSV
    import csv
    fieldnames = ["subject", "body", "sender", "label", "confidence", "source"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(deduped)

    log.info("Dataset saved to: %s  (%d rows)", output_path, len(deduped))
    print(f"\nDataset ready: {output_path}")
    print(f"Total samples: {len(deduped)}")
    print(f"Label distribution: {dict(label_counts)}")


if __name__ == "__main__":
    main()

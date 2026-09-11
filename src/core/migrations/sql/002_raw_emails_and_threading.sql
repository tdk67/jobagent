-- 002_raw_emails_and_threading.sql: Raw email message cache and application threading support

CREATE TABLE IF NOT EXISTS raw_emails (
    entry_id TEXT PRIMARY KEY,
    folder TEXT NOT NULL,
    sender_name TEXT,
    sender_email TEXT,
    subject TEXT NOT NULL,
    body TEXT,
    preview TEXT,
    received_time TEXT NOT NULL,
    iso_week TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Performance and query indexes for weekly incremental syncing
CREATE INDEX IF NOT EXISTS idx_raw_emails_received_time ON raw_emails(received_time);
CREATE INDEX IF NOT EXISTS idx_raw_emails_folder ON raw_emails(folder);
CREATE INDEX IF NOT EXISTS idx_raw_emails_iso_week ON raw_emails(iso_week);

-- Ensure canonical company index on applications
CREATE INDEX IF NOT EXISTS idx_applications_company_lower ON applications(LOWER(company));

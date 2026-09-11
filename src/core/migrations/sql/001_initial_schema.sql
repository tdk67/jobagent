-- 001_initial_schema.sql: Initial JobAgent relational database schema

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    applied_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Applied',
    source TEXT DEFAULT 'Direct',
    job_url TEXT,
    location TEXT,
    salary_info TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS email_interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER,
    entry_id TEXT UNIQUE,
    sender_name TEXT,
    sender_email TEXT,
    subject TEXT,
    received_time TEXT,
    category TEXT NOT NULL,
    preview TEXT,
    confidence_score REAL DEFAULT 1.0,
    action_taken TEXT,
    FOREIGN KEY (application_id) REFERENCES applications (id)
);

CREATE TABLE IF NOT EXISTS interviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER,
    entry_id TEXT,
    company TEXT NOT NULL,
    role TEXT,
    interview_date TEXT,
    interview_type TEXT DEFAULT 'Phone Screen',
    meeting_link TEXT,
    status TEXT DEFAULT 'Scheduled',
    notes TEXT,
    FOREIGN KEY (application_id) REFERENCES applications (id)
);

CREATE TABLE IF NOT EXISTS qa_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_key TEXT UNIQUE,
    question_text TEXT NOT NULL,
    answer TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    verified INTEGER DEFAULT 1,
    provenance TEXT DEFAULT 'user_verified',
    updated_at TEXT NOT NULL
);

-- Performance & Integrity Indexes
CREATE INDEX IF NOT EXISTS idx_applications_company ON applications(company);
CREATE INDEX IF NOT EXISTS idx_applications_applied_date ON applications(applied_date);
CREATE INDEX IF NOT EXISTS idx_interviews_company ON interviews(company);
CREATE INDEX IF NOT EXISTS idx_interviews_interview_date ON interviews(interview_date);
CREATE INDEX IF NOT EXISTS idx_email_interactions_entry_id ON email_interactions(entry_id);

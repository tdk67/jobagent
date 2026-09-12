-- 003_approvals_and_cycles.sql: Human approval requests and autonomous cycle execution state

CREATE TABLE IF NOT EXISTS pending_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    context TEXT,
    urgency TEXT DEFAULT 'normal',
    status TEXT DEFAULT 'pending',
    response TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_pending_approvals_status ON pending_approvals(status);

CREATE TABLE IF NOT EXISTS agent_cycles (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    status TEXT NOT NULL,
    triage_result TEXT,
    reports_result TEXT,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_cycles_status ON agent_cycles(status);

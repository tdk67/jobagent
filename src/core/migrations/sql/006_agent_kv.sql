-- 006_agent_kv.sql: Simple persistent key-value store for agent runtime state
-- (e.g. event-loop watermark: highest raw email entry_id already processed).

CREATE TABLE IF NOT EXISTS agent_kv (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL
);
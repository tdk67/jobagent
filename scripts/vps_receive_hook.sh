#!/usr/bin/env bash
# JobAgent — VPS receive hook: atomically install a pushed snapshot and refresh the A2A gateway.
#
# How it's invoked: (from the local PC, via SSH) after rsync lands files in ~/jobagent-sync/incoming/
#   ssh root@<vps> 'bash /root/jobagent/scripts/vps_receive_hook.sh <source>'
#
# <source> identifies where files came from so we can log provenance:
#   pc-inbox   → DB pushed from the local PC (the normal phone-mirror path)
#   telegram   → DB delivered as a Telegram attachment
#
# Safety: never merges; validates the DB before swapping. Old DB is kept as .prev for rollback.
set -euo pipefail

SRC="${1:-pc-inbox}"
ROOT_DIR="/root/jobagent"
INCOMING="$ROOT_DIR/sync/incoming"
BACKUP_DIR="$ROOT_DIR/sync/backups"
LOG="$ROOT_DIR/sync/sync.log"
STAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$INCOMING" "$BACKUP_DIR"

log() { echo "[$STAMP] $*" >> "$LOG"; echo "$*"; }

# ── 1. Find the incoming fresh DB ───────────────────────────────────────
DB_IN="$INCOMING/jobagent.db"
if [[ ! -f "$DB_IN" ]]; then
  log "❌ no $DB_IN — nothing to install"
  exit 1
fi

# ── 2. Validate it's a real SQLite DB before touching anything ──────────
if ! sqlite3 "$DB_IN" "PRAGMA integrity_check;" 2>/dev/null | grep -q "^ok$"; then
  log "❌ incoming DB failed integrity check — aborting, keeping existing"
  exit 1
fi

# Quick sanity: must contain the expected tables
TPLIST=$(sqlite3 "$DB_IN" "SELECT name FROM sqlite_master WHERE type='table';" 2>/dev/null | tr '\n' ' ')
for t in applications email_interactions interviews qa_memory; do
  if ! echo "$TPLIST" | grep -qw "$t"; then
    log "❌ incoming DB missing expected table '$t' — aborting"
    exit 1
  fi
done

# ── 3. Backup current DB (keep last 3) ──────────────────────────────────
CUR="$ROOT_DIR/data/jobagent.db"
if [[ -f "$CUR" ]]; then
  cp "$CUR" "$BACKUP_DIR/jobagent_$STAMP.db"
  ls -1t "$BACKUP_DIR"/jobagent_*.db 2>/dev/null | tail -n +4 | xargs -r rm -f
  log "◀ backed up current DB → sync/backups/jobagent_$STAMP.db"
fi

# ── 4. Atomic swap: validate → move → verify running DB ─────────────────
mv "$DB_IN" "$CUR"
log "✓ installed new DB ($(du -h "$CUR" | cut -f1), source=$SRC)"

# ── 5. Also install profile/config if present ────────────────────────────
for f in profile.json config.local.json; do
  if [[ -f "$INCOMING/$f" && ! -f "$ROOT_DIR/$f" ]]; then
    cp "$INCOMING/$f" "$ROOT_DIR/$f"
    log "▶ installed $f (first-time only; never overwrites existing local file)"
  fi
done
# clean consumed payloads
rm -f "$INCOMING/jobagent.db" "$INCOMING/profile.json" "$INCOMING/config.local.json" 2>/dev/null || true

# ── 6. Refresh the running A2A gateway so the phone sees new data ────────
if command -v pm2 >/dev/null 2>&1; then
  pm2 restart jobagent-a2a --update-env >/dev/null 2>&1 && log "⟳ restarted jobagent-a2a (pm2)" || log "⚠ pm2 restart failed"
else
  pkill -f "run_agent.py --server" 2>/dev/null || true
  (cd "$ROOT_DIR" && nohup venv/bin/python run_agent.py --server > /tmp/jobagent-a2a.log 2>&1 &) 
  log "⟳ restarted jobagent-a2a (nohup)"
fi

# ── 7. Verify ───────────────────────────────────────────────────────────
for _ in 1 2 3 4 5 6; do sleep 5; curl -sf http://127.0.0.1:8765/health >/dev/null 2>&1 && break; done
if curl -sf http://127.0.0.1:8765/health >/dev/null 2>&1; then
  log "✅ gateway healthy"
else
  log "⚠ gateway not healthy after restart — check pm2 logs"
fi
log "── sync complete (source=$SRC) ──────────────"
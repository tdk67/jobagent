# F7 — Final regression & judge-readiness sweep (worker evidence)

Date: 2026-09-12. Repo: /root/jobagent, branch main @ HEAD `05bbb78` (F6 status commit,
working tree clean). No code changes made — evidence-only task.

## 1. Full test suite, twice in a row (flakiness check)

Command: `timeout 600 venv/bin/python -m pytest tests/ -q`

Run 1:
```
49 passed, 1 warning in 27.41s
```
Run 2:
```
49 passed, 1 warning in 25.54s
```
Both runs identical (49 passed) — no flakiness observed. (The single warning is a
starlette/anyio `BlockingPortal` deprecation; present at baseline.)

## 2. PII scan across all history (using local pattern file)

Command: `timeout 120 git grep -i -f logs/tasks/pii_patterns.txt $(git rev-list --all) --`
then `grep -v classifier.py` on the output.

Result: `git grep` exit=1 (no matches). 0 lines before filter, 0 lines after filtering out
`classifier.py` (whose generic domain blocklist is the single allowed exception per plan).

Scanner self-verification (prove the scan is meaningful, not a no-op): a scratch git repo
containing a line with a token from the pattern file is matched with exit=0; without such a
token the same command exits 1. So a clean result genuinely means no real-PII tokens matched
in any commit of this repo's history.

NOTE: the pattern file's contents (real-PII-derived tokens: a name, an email prefix, a phone
number, two address fragments, a postal code, two CV filenames) are local-only and gitignored
(`logs/`), and are deliberately NOT reproduced in this committed evidence file.

## 3. Secret scan across all history

Command: `timeout 120 git grep -n -E "sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}" $(git rev-list --all)`

Result: `git grep` exit=1 (no matches), 0 lines. Clean.

## 4. End-to-end demo on a COPY (never the real DB)

Per plan: `cd /tmp && cp -r /root/jobagent ja_demo && cd ja_demo && timeout 300 venv/bin/python run_agent.py --demo`
(the copy's own venv resolved; playwright ran fine inside the copy context).

Demo exit code: **0**. Verified program outputs:

```
[Step 1/4] Seeding Candidate Applications & Profile...
  ✓ Applications logged in isolated demo SQLite CRM

[Step 2/4] Archiving Job Posting (Dual-Asset: Markdown + PDF Snapshot)...
  ✓ Clean Markdown: /tmp/ja_demo/data/archives/Chrono24_Senior_Java_Developer_20260911_114018.md
  ✓ High-Res Visual PDF: /tmp/ja_demo/data/snapshots/Chrono24_Senior_Java_Developer_20260911_114018.pdf

[Step 3/4] Ingesting Inbox Emails & Detecting Genuine Interviews...
  ✓ Emails Scanned: 3
  ✓ Interviews Detected: 1
  ✓ Rejections Processed: 1
  ✓ Sales Spam Discarded: 1

[Step 4/4] Generating Multi-Stakeholder Compliance & Proof Reports...
  ✓ Generated DASHBOARD: /tmp/ja_demo/output/dashboard_report.pdf
  ✓ Generated AFA_TABLE: /tmp/ja_demo/output/afa_table_report.pdf
  ✓ Generated AGENCY_SUMMARY: /tmp/ja_demo/output/agency_summary_report.pdf

🏆 SUMMARY: JobAgent ran autonomously in the background.
🤖 LLM AGENT BRIEFING: [Deterministic Fallback] Processed 3 messages. Found 1 interviews, 1 rejections.
🔔 HUMAN ATTENTION REQUIRED:
   👉 Interview Invitation: Chrono24 (Einladung zum Vorstellungsgespräch: Senior Java Developer)
      Meeting Link: https://teams.microsoft.com/l/meetup-join/demo-chrono24
```

All four expected outcomes confirmed: interview detected (1), rejection processed (1), noise
filtered (1), reports generated (3 PDFs). The run used the F4 deterministic fallback with two
expected loud warnings at startup (Gmail adapter unwired; no LLM provider configured) — that is
the intended fail-loud behavior when no credentials are present, not an error. Demo DB stayed
isolated in `/tmp/ja_demo/data/jobagent_demo.db`; copy removed afterwards; real
`data/jobagent.db` never touched.

## 5. Server smoke test (timeout-bounded, background, killed afterwards)

Startup: `A2A_PORT=8799 timeout 120 venv/bin/python run_agent.py --server --port 8799 &`
Verified listening on **127.0.0.1:8799 only** (ss: `127.0.0.1:8799`), token issued in startup log.

| # | Check | Result |
|---|-------|--------|
| 1 | `curl -m 5 http://127.0.0.1:8799/health` | HTTP 200 `{"status":"ok","agent":"JobAgent","version":"1.0.0"}` |
| 2 | pair with `Host: evil.com` | HTTP 403 `{"detail":"Invalid Host header"}` |
| 3 | pair with `Host: 127.0.0.1:8799` | HTTP 200 `{"token":"5d776c...","status":"paired"}` (token redacted to prefix) |
| 4 | unauth `/a2a/v1/capabilities` | HTTP 401 |
| 5 | authed `/a2a/v1/capabilities` (Bearer) | HTTP 200, capability list returned (`triage_emails`, `arch…`) |
| 6 | server kill | `pkill` on the pid; port 8799 free afterwards; no `run_agent.py --server` process remains; port still free 60s later (the 120s outer `timeout` bound held even if kill had failed) |

## 6. Judge-readiness summary

- **Strands usage:** JobAgent is built on AWS Strands SDK — `strands.Agent` coordinator in
  `src/agent/coordinator.py` with session-bound @tools (ingest/archive/report/etc.), exposed
  A2A agent card (`/a2a/v1/capabilities` returns the automatic description), and the
  gateway/auth flow exercised end-to-end in section 5. When no LLM credentials are present,
  the coordinator now runs a clearly-labeled deterministic tool-only mode (F4 fail-loud)
  instead of silently attempting doomed model calls.
- **Autonomy story:** one command (`python run_agent.py --demo`, or `--server` for the
  extension) archives job postings (Markdown + high-res PDF snapshot), ingests the inbox,
  detects interviews/rejections/spam, updates the CRM, and renders the statutory AfA proof
  reports — all demonstrated in section 4. The Chrome extension pairs with the localhost
  gateway over a hardened channel (F2/F3 security fixes in place, verified in section 5).
- **Privacy story:** storage is 100% local SQLite; the gateway binds loopback-only, validates
  Host headers against DNS rebinding, logs pairings, and rejects non-loopback clients
  (F3). History is PII-clean (F1 purge + sections 2–3), no secrets in any commit, and the
  README discloses that LLM inference sends only the profile context needed for form
  reasoning/email classification to the configured provider (F6). All 49 tests pass twice
  in a row; every remediation task F1–F7 verified end-to-end.
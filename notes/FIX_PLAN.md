# JobAgent FIX_PLAN — post-review remediation (F2–F7)

**Context:** Full code review on 2026-09-12 (after commit `362aead`) found: an active PII
leak (F1 — ALREADY FIXED by history squash, commit `04e93ae`), extension/gateway security
holes, dead code masking failures, correctness bugs, and data-integrity risks in the
statutory AfA report path. This plan remediates everything else.

**Ground rules for ALL tasks:**
- Repo: `/root/jobagent`. Python: `venv/bin/python`. Test cmd (ALWAYS wrapped in timeout):
  `timeout 600 venv/bin/python -m pytest tests/ -q`  (~35s, 27 tests at baseline).
- NEVER introduce real personal data anywhere. All fixtures must use dummy data
  (Jane Doe / example.com / +49 150 0000000 / Musterstrasse 1, 60311 Frankfurt am Main).
- No silent `except: pass`, no fallbacks that mask real errors. Errors must be loud
  (log.warning minimum) or raised.
- Remote is SSH (`git@github.com:tdk67/jobagent.git`), branch `main`. Workers NEVER
  commit/push; QA gates commits.
- Scope discipline: touch only files listed in your task. Record deviations in evidence.
- Evidence files and anything that gets committed must NEVER contain real PII strings —
  if a scan "finds" something, redact it in the evidence (e.g. "[REDACTED-PII]: <file>:<line>").
- `logs/` is gitignored — never remove that entry; worker/QA logs stay local.

---

## F2 — Extension message-channel security (review findings S1, S3)

**Problem:**
1. `extension/popup.js` broadcasts the autofill payload — containing `apiToken`, the FULL
   candidate profile, and base64 CV/cover-letter documents — via
   `window.postMessage({type:"JOBAGENT_AUTOFILL_BROADCAST", data}, "*")` injected into
   ALL frames of arbitrary job-portal pages. Any third-party iframe (ads/analytics) can
   read it and then call the gateway itself.
2. `extension/content.js` has a `window.addEventListener("message", ...)` accepting
   `JOBAGENT_AUTOFILL_BROADCAST` from ANY origin/page script.

**Fix:**
- Delete the entire `chrome.scripting.executeScript(... postMessage ...)` broadcast block
  in popup.js. `chrome.tabs.sendMessage` (runtime messaging, invisible to page scripts)
  already reaches content scripts in ALL frames of the tab — the broadcast is redundant.
- Remove `apiToken` from the payload sent to content.js (content.js never uses it — the
  popup-side runtime bridge `request_gateway_reason` adds the Authorization header itself).
  Keep `gatewayUrl`, `profile`, `documents` (runtime messages are extension-private).
- Delete the `window "message"` listener block in content.js entirely.

**Files:** `extension/popup.js`, `extension/content.js`

**Verification points:**
1. `grep -rn "JOBAGENT_AUTOFILL_BROADCAST" extension/` → NO hits.
2. `grep -rn "postMessage" extension/` → NO hits.
3. `grep -n "apiToken" extension/content.js` → NO hits; popup.js payload object no longer
   contains apiToken.
4. Runtime-message path intact: content.js still handles `autofill_form` via
   `chrome.runtime.onMessage`; popup.js still sends via `chrome.tabs.sendMessage` and
   still does the all-frames `ensureContentScriptInjected`.
5. Full test suite green.

---

## F3 — Gateway auth hardening (review findings S2 + DNS rebinding + Docker exposure)

**Problem:**
1. `GET /api/v1/auth/pair` hands the live API token to ANY loopback caller. Combined with
   no `Host` header validation, a DNS-rebinding webpage can pair itself and exfiltrate
   profile + CV documents.
2. Dockerfile CMD binds `0.0.0.0`, docker-compose publishes `8765:8765` → whole PII API
   exposed to the LAN.

**Fix:**
- In `src/a2a/server.py`: add a middleware (or dependency applied to ALL `/api/*` and
  `/a2a/*` routes) validating the `Host` header is one of
  `127.0.0.1[:port]`, `localhost[:port]`, `[::1][:port]`, or the configured
  `cfg.a2a.host[:port]`. Reject anything else with HTTP 403 (`"Invalid Host header"`).
  This kills DNS rebinding regardless of client IP.
- Keep the loopback client-IP check on `/api/v1/auth/pair`; additionally log every
  successful pairing (`log.info("Extension paired from %s", client_host)`).
- `Dockerfile`: change CMD to `--host 127.0.0.1`. `docker-compose.yml`: publish
  `"127.0.0.1:8765:8765"`. Add a comment: to expose on LAN, set `A2A_HOST` / override
  the port mapping deliberately.
- `run_agent.py --server`: honor env `A2A_HOST`/`A2A_PORT` as override order:
  CLI flag > env > config (see F6 for config wiring; here just read `os.getenv`).

**Files:** `src/a2a/server.py`, `Dockerfile`, `docker-compose.yml`, `run_agent.py`,
`tests/test_a2a.py`

**Verification points:**
1. New tests in `tests/test_a2a.py`:
   - request with header `Host: evil.example.com` to `/api/v1/auth/pair` AND to an
     authenticated route (`/api/v1/profile` with valid token) → 403.
   - request with `Host: 127.0.0.1:8765` (TestClient default `testserver` must be allowed
     OR tests set Host explicitly — pick one and document) → pair returns token.
   - non-loopback client → 403 on pair (existing behavior, keep covered).
2. `grep -n "0.0.0.0" Dockerfile docker-compose.yml` → no hits (compose healthcheck uses
   `localhost`, fine).
3. Full suite green, no existing test broken (adjust TestClient base_url/headers as needed,
   but do NOT weaken the Host check to make tests pass — set proper Host headers in tests).

---

## F4 — Correctness: city bug, IMAP dates, dead LLM fallback, Gmail no-op, model fail-loud

**Problems & fixes (5 independent items, one commit):**
1. **City bug** — `src/tools/form/reasoner.py` `_match_core_profile` city branch uses
   `pers.address.split(",")[0]` (= street!). Fix: return `pers.city` (fall back to
   parsing the address segment that contains the postal code, NOT segment 0).
   Same bug in `extension/content.js` localFallbackFill city branch: use `pers.city`,
   fallback `pers.address.split(",")[1]` trimmed of the leading postal code.
2. **IMAP ignores date range** — `src/tools/email/adapters.py` `ImapAdapter.fetch_emails`
   accepts `start_date`/`end_date` but only uses `cutoff_date`. Fix: translate
   start/end (via `parse_flexible_date`) into IMAP `SEARCH SINCE <dd-Mon-yyyy>` /
   `BEFORE <dd-Mon-yyyy>` criteria (IMAP dates are `01-Sep-2026` format), keeping the
   existing client-side `cutoff_date` filter as second guard. Extract the date→IMAP-criteria
   building into a pure helper `build_imap_search_criteria(start_date, end_date, cutoff_date)`
   at module level and unit-test THAT (no live IMAP needed).
3. **LLM triage fallback is dead** — `classify(enable_llm_fallback=...)` is never enabled.
   Fix: add `llm_fallback: bool = False` to `EmailIngestionConfig` in `src/core/config.py`;
   `EmailIngestEngine.run_triage` passes `enable_llm_fallback=self.config.email_ingestion.llm_fallback`
   into `classifier.classify(...)`. Document the flag in `config.example.json`.
4. **Gmail adapter silent no-op** — `src/tools/email_ingest_tool.py` constructs
   `GmailMcpAdapter(mcp_client=None)` whenever `gmail.enabled` (default True) → always
   returns [] with a debug log. Fix: when `enabled` but no MCP client can be constructed,
   emit `log.warning("Gmail ingestion enabled in config but no MCP client is wired — "
   "adapter will fetch nothing")` ONCE at engine construction, and do not append the
   dead adapter to self.adapters.
5. **Strands model fail-loud** — `src/agent/coordinator.py`: `Agent(model=None)` silently
   defaults to a BedrockModel, so `getattr(self.agent, "model", None)` is always truthy
   and every cycle attempts a doomed LLM call when no creds exist. Fix: compute
   `self.llm_available: bool` in `_init_strands_agent` (True only if a provider was
   explicitly initialized with credentials). `run_autonomous_cycle` gates the agent-reasoning
   branch on `self.llm_available`; when False log ONE loud warning at construction:
   "No LLM provider configured (set GEMINI_API_KEY or AWS credentials) — running
   deterministic tool-only mode". Update `tests/test_autonomous_agent.py`: the fallback
   test must set `coordinator.llm_available = False` instead of `agent.model = None`.

**Files:** `src/tools/form/reasoner.py`, `extension/content.js`,
`src/tools/email/adapters.py`, `src/core/config.py`, `config.example.json`,
`src/tools/email_ingest_tool.py`, `src/agent/coordinator.py`,
`tests/test_autonomous_agent.py`, `tests/test_form_reasoner.py`, new test additions where named.

**Verification points:**
1. New test: reasoner maps a field labeled `"City"` / `"Ort"` to `profile.personal.city`
   (e.g. "Frankfurt am Main"), NOT the street. Same for label "Stadt".
2. New tests for `build_imap_search_criteria`: start+end → `SINCE 01-Sep-2026 BEFORE 08-Sep-2026`;
   None/None → `ALL`; cutoff only → `SINCE ...`.
3. New test: `run_triage` with `llm_fallback=True` config passes `enable_llm_fallback=True`
   to classify (monkeypatch `EmailClassifier.classify` to capture kwargs).
4. New/updated test: coordinator constructed with no provider creds → `llm_available is
   False`; `run_autonomous_cycle` completes via deterministic path WITHOUT attempting an
   agent LLM call (monkeypatch `coordinator.agent` with a Mock that raises if called).
5. `grep -n "mcp_client=None" src/tools/email_ingest_tool.py` → dead adapter no longer
   appended (either removed or guarded by the loud warning path).
6. Full suite green.

---

## F5 — Data integrity: no fabricated data in statutory/compliance paths

**Problems & fixes:**
1. `src/core/storage.py` `import_from_summary`: unparseable roles default to
   `"Senior Software Engineer"` — fabricated data in the AfA Eigenbemühungsnachweis.
   Fix: default to `"Unbekannt (bitte prüfen)"`; when the application ALREADY exists,
   do NOT overwrite a real role with the unknown placeholder. Same for the interviews
   import branch (`"Senior Software Engineer"` default there too).
2. `run_agent.py` `--report` path: remove the hidden auto-import magic block
   (`if len(existing_apps) <= 2 and default_sum.exists() ...`) and the hardcoded
   `C:/Data/work/jobSearch/...` default. `--import-summary` keeps working but its
   `const=` default becomes `None` → if flag given without value, print usage error
   ("--import-summary requires a path") and exit 2.
3. `extension/content.js` `localFallbackFill`: remove hardcoded fabrications for legally
   significant questions — work authorization (`val = "Ja"`) and previously-employed
   (`val = "Nein"`). Instead: leave the field EMPTY and mark it visibly for human review
   (reuse the dashed-border + title pattern: `el.style.border="2px dashed #f59e0b";
   el.title="⚠️ Legally significant question — please answer manually"`). Salary/notice
   period may still autofill from the profile but get the same confirm-marking.

**Files:** `src/core/storage.py`, `run_agent.py`, `extension/content.js`,
`tests/test_storage.py`

**Verification points:**
1. New test in `tests/test_storage.py`: `import_from_summary` with a summary entry whose
   subject yields no parseable role → stored role == "Unbekannt (bitte prüfen)";
   second import pass does NOT overwrite an existing real role ("Backend Engineer") with
   the placeholder.
2. `grep -n "Senior Software Engineer" src/core/storage.py run_agent.py` → no hits.
3. `grep -n "Auto-importing\|C:/Data" run_agent.py` → no hits.
4. `grep -n '"Ja"\|"Nein"' extension/content.js` → no hardcoded answers for
   authorization/employment questions remain (select-matching helpers in
   `applyValueToElement` legitimately map yes/no values — those stay; the fabrication
   is only in localFallbackFill's `val =` assignments).
5. `run_agent.py --import-summary` (no value) → exits non-zero with usage message
   (test via `timeout 30 venv/bin/python run_agent.py --import-summary; echo $?` — must
   NOT be 0, and must not touch the DB).
6. Full suite green.

---

## F6 — Dead config, duplicate tools, contract & docs hygiene

**Problems & fixes:**
1. `.env.example` declares `IMAP_HOST`, `IMAP_PORT`, `GMAIL_APP_PASSWORD`,
   `OPENAI_API_KEY`, and compose sets `A2A_HOST` — none are read anywhere. Fix:
   - Wire env overrides in `src/core/config.py` `load_config()`: after file merge, apply
     `IMAP_HOST`, `IMAP_PORT` (int), `IMAP_USE_SSL` (bool "1/true/yes"), `A2A_HOST`,
     `A2A_PORT` (int), `JOBAGENT_DB` (storage.database_path) if set. Precedence:
     env > config.local.json > config.example.json > defaults.
   - Remove `OPENAI_API_KEY` and `GMAIL_APP_PASSWORD` from `.env.example` (unused; do not
     advertise config that doesn't exist). Keep IMAP_USER/IMAP_PASSWORD (used by adapters).
2. Duplicate Strands `@tool` definitions: module-level `ingest_emails`
   (`src/tools/email_ingest_tool.py`), `archive_job_posting` (`src/tools/job_archive_tool.py`),
   `generate_compliance_report` (`src/tools/report_render_tool.py`) duplicate the
   coordinator's session-bound closures and are used by nobody. Delete the three
   module-level `@tool` functions (keep the engine classes). Check no test imports them
   first; if a test does, migrate the test to the coordinator tools.
3. `src/a2a/server.py` `delegate_task`: the `HTTPException(400)` for unknown actions is
   swallowed by the generic `except Exception` → HTTP 200 `status:"failed"`. Fix:
   `except HTTPException: raise` before the generic handler. Add test: unknown action →
   HTTP 400.
4. `README.md`: (a) replace the hardcoded "26 unit and integration tests" with the
   current count or a version-neutral phrase ("the full test suite under tests/");
   (b) in the Privacy section, qualify the "100% local" claim: storage is 100% local, but
   LLM inference (Gemini/Bedrock) necessarily sends profile context needed for form
   reasoning / email classification to the configured provider — state this plainly;
   (c) document the new env overrides from item 1.

**Files:** `src/core/config.py`, `.env.example`, `src/tools/email_ingest_tool.py`,
`src/tools/job_archive_tool.py`, `src/tools/report_render_tool.py`, `src/a2a/server.py`,
`tests/test_a2a.py`, `tests/test_config.py`, `README.md`

**Verification points:**
1. New tests in `tests/test_config.py`: with monkeypatched env `IMAP_HOST=imap.test` /
   `A2A_PORT=9999`, `load_config()` reflects them; without env, file/default values win.
2. `grep -rn "def ingest_emails\|def archive_job_posting\|def generate_compliance_report" src/tools/`
   → no module-level @tool duplicates (only coordinator closures in src/agent/coordinator.py).
3. New test: POST `/a2a/v1/tasks` with `action="bogus"` (authed) → HTTP 400.
4. `grep -n "OPENAI_API_KEY\|GMAIL_APP_PASSWORD" .env.example` → no hits.
5. `grep -n "26 unit" README.md` → no hits; README privacy section mentions provider
   inference disclosure (`grep -n "configured provider" README.md`).
6. Full suite green.

---

## F7 — Final regression & judge-readiness sweep (last task)

**Scope:** no feature work. Verify the whole remediation end-to-end and produce the
final evidence pack before the Sept 14 deadline.

**Steps (worker performs, QA re-performs):**
1. Full suite twice in a row (catch flakiness): `timeout 600 venv/bin/python -m pytest tests/ -q`.
2. PII scan (must be CLEAN except classifier.py's generic domain blocklist). Use the
   pattern file `logs/tasks/pii_patterns.txt` (local-only, gitignored — never copy its
   contents into any committed file):
   `git grep -i -f logs/tasks/pii_patterns.txt $(git rev-list --all) -- | grep -v classifier.py`
3. Secret scan: `git grep -n -E "sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}" $(git rev-list --all)` → clean.
4. End-to-end demo on a COPY (never the real DB):
   `cd /tmp && cp -r /root/jobagent ja_demo && cd ja_demo && timeout 300 venv/bin/python run_agent.py --demo`
   (venv is inside the repo copy; if playwright browsers missing in copy context, run from
   /root/jobagent directly — --demo uses its own isolated `data/jobagent_demo.db`).
   Verify: interview detected (1), rejection processed (1), noise filtered (1), reports
   generated, exit 0.
5. Server smoke: start `--server` on port 8799 (timeout-bounded, background), then:
   - `curl -m 5 http://127.0.0.1:8799/health` → 200 ok
   - pair with `Host: evil.com` → 403; with `Host: 127.0.0.1:8799` → token
   - unauth `/a2a/v1/capabilities` → 401; authed → 200
   Kill the server afterwards.
6. Write `notes/evidence/F7-final-check.md` with all pasted outputs + a short
   judge-readiness summary (Strands usage, autonomy story, privacy story).
7. If any step fails: do NOT paper over it — mark F7 blocked with the failing evidence.

**Files:** none (evidence only). QA commits the evidence file.

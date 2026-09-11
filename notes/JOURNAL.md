# JobAgent JOURNAL (append-only)

## 2026-09-12 — F1 done (PII purge, by lead agent)
Real personal data (name, home address, personal email, mobile, CV filenames) was committed
in `tests/test_cover_letter.py` (old commit 362aead) and pushed to the public repo.
What changed: fixture rewritten to Jane Doe dummy data (test still passes); entire history
squashed into orphan commit `04e93ae` with GitHub-noreply author; force-pushed; old commit
verified unreachable from a fresh clone; local reflog expired + gc pruned.
Lesson: any fixture copied from a local profile must be scrubbed before commit — add the
`logs/tasks/pii_patterns.txt` grep to pre-commit habits.

## 2026-09-12 — F2 done (extension message-channel security)
Commit `4f6a0d6`. Removed the `window.postMessage({type:"JOBAGENT_AUTOFILL_BROADCAST", data}, "*")`
broadcast block from popup.js (exposed apiToken + full profile + base64 CV to all frames including
third-party iframes). Removed the corresponding `window.addEventListener("message", ...)` listener
in content.js. Stripped `apiToken` from the content-script payload (content.js never used it;
popup-side bridge adds the Authorization header itself). Runtime-message path (`chrome.tabs.sendMessage`
+ `chrome.runtime.onMessage`) preserved — reaches all frames via extension-private messaging invisible
to page scripts.
Evidence: `notes/evidence/F2-qa.md`. Tests: full suite (27 passed, no new tests needed — extension
is pure JS with no Python test harness).
Lesson: `window.postMessage("*")` is a security anti-pattern for sensitive payloads; Chrome extension
runtime messaging (`chrome.tabs.sendMessage` / `chrome.runtime.onMessage`) is the correct channel
since it is invisible to page scripts and third-party iframes.

## 2026-09-12 — F3 done (gateway auth hardening)
Commit `78d425f`. Added HTTP middleware validating the `Host` header on all `/api/*` and `/a2a/*`
routes — only loopback hosts (`127.0.0.1`, `localhost`, `[::1]`) or the configured `cfg.a2a.host`
are allowed; anything else → HTTP 403 `"Invalid Host header"`. This defeats DNS-rebinding attacks
where a malicious webpage's JavaScript connects to the loopback-bound gateway but sends its own
domain as the Host header. Dockerfile CMD changed from `--host 0.0.0.0` to `--host 127.0.0.1`;
docker-compose.yml port mapping changed from `8765:8765` (all interfaces) to `127.0.0.1:8765:8765`
(loopback only). The `/api/v1/auth/pair` endpoint now logs every successful pairing
(`log.info("Extension paired from %s", client_host)`). `run_agent.py --server` now honors env
`A2A_HOST`/`A2A_PORT` with override order CLI flag > env > config, and writes the effective values
back to `cfg.a2a` so the middleware stays in sync with the bind address.
Evidence: `notes/evidence/F3-qa.md`. Tests: 5 new tests in `tests/test_a2a.py`:
`test_host_header_dns_rebinding_rejected`, `test_host_header_loopback_allowed_pair_returns_token`,
`test_host_header_localhost_and_ipv6_variants_allowed`, `test_host_header_configured_a2a_host_allowed`,
`test_auth_pair_rejects_non_loopback_client`. Full suite: 32 passed (27 baseline + 5 new).
Lesson: DNS rebinding is a real threat even for loopback-bound services — a browser can be tricked
into resolving an attacker's domain to 127.0.0.1, and the Host header will reveal the attacker's
domain. Validating the Host header is a simple, effective defense that works regardless of client IP.

## 2026-09-12 — F4 done (correctness fixes)
Commit `7ee5e90`. Fixed five independent correctness bugs: (1) city extraction now returns
`pers.city` with fallback to the postal-code-bearing address segment instead of the street
(segment 0); (2) IMAP date range now wired via `build_imap_search_criteria(start_date, end_date,
cutoff_date)` helper producing `SINCE dd-Mon-yyyy BEFORE dd-Mon-yyyy` criteria; (3) LLM triage
fallback flag `llm_fallback: bool = False` added to `EmailIngestionConfig` and wired through
`run_triage` to `classifier.classify(enable_llm_fallback=...)`; (4) Gmail dead-adapter guard:
when `gmail.enabled` but no MCP client is wired, logs a loud warning and does NOT append a
dead `GmailMcpAdapter(mcp_client=None)`; (5) Strands model fail-loud: `self.llm_available`
computed in `_init_strands_agent` (True only when Gemini or Bedrock successfully initialize
with credentials), gates the agent-reasoning branch in `run_autonomous_cycle`.
Evidence: `notes/evidence/F4-qa.md`. Tests: 10 new tests across `tests/test_form_reasoner.py`
(2 city tests), `tests/test_email_ingest.py` (4 IMAP criteria tests, 2 llm_fallback tests,
1 Gmail dead-adapter test), `tests/test_autonomous_agent.py` (1 new no-creds test + 2 updated
fallback tests). Full suite: 42 passed (32 baseline + 10 new).
Lesson: Silent failures (dead adapters, ignored config flags, doomed LLM calls) are harder to
debug than loud warnings. Gate expensive operations on explicit availability checks, and log
warnings when expected resources are missing.

## 2026-09-12 — F5 done (data integrity in statutory/compliance paths)
Commit `8942d86`. Three problems fixed: (1) `import_from_summary` defaulted unparseable roles
to fabricated "Senior Software Engineer" — now uses `UNKNOWN_ROLE = "Unbekannt (bitte prüfen)"`
and never overwrites an existing real role with the placeholder; (2) `run_agent.py --report`
had a hidden auto-import block with hardcoded `C:/Data/work/jobSearch/...` path — removed
entirely, `--import-summary` now requires an explicit path (exit 2 if omitted); (3) extension
`localFallbackFill` hardcoded `val = "Ja"` for work authorization and `val = "Nein"` for
previously-employed — now leaves these legally significant questions empty and marks them with
dashed amber border + "⚠️ Legally significant question — please answer manually" tooltip.
Salary/notice period autofill from profile but get the same confirm-marking.
Evidence: `notes/evidence/F5-qa.md`. Tests: 3 new tests in `tests/test_storage.py`:
`test_import_from_summary_unparseable_role_uses_unknown_placeholder`,
`test_import_from_summary_does_not_overwrite_real_role_with_placeholder`,
`test_import_from_summary_interviews_use_unknown_role_placeholder`. Full suite: 45 passed
(42 baseline + 3 new).
Lesson: In compliance-sensitive paths (statutory AfA reports, legally significant form
questions), fabricated defaults are worse than empty fields. Use explicit "unknown" placeholders
and visible markers to force human review.

## 2026-09-12 — F6 done (dead config wiring, duplicate @tool removal, 400 contract fix, README claims)
Commit `174a874`. Four problems fixed: (1) Six environment variables declared in .env.example
but never read by config.py — wired IMAP_HOST, IMAP_PORT (int-validated), IMAP_USE_SSL
(bool "1/true/yes"), A2A_HOST, A2A_PORT (int-validated), JOBAGENT_DB into load_config()
with precedence env > config.local.json > config.example.json > defaults; invalid ints logged
as warnings and ignored (not silent failure). (2) Three duplicate module-level @tool functions
(ingest_emails in email_ingest_tool.py, archive_job_posting in job_archive_tool.py,
generate_compliance_report in report_render_tool.py) duplicated the coordinator's session-bound
closures and were used by nobody — deleted all three (engine classes retained), removed unused
imports (json, from strands import tool). (3) POST /a2a/v1/tasks with unknown action returned
HTTP 200 status:"failed" because HTTPException(400) was swallowed by generic except Exception —
added `except HTTPException: raise` before the generic handler. (4) .env.example removed unused
OPENAI_API_KEY and GMAIL_APP_PASSWORD (don't advertise config that doesn't exist), kept
IMAP_USER/IMAP_PASSWORD (used by adapters); README.md replaced hardcoded "26 unit and integration
tests" with version-neutral language, added LLM provider-inference disclosure in Privacy section
("LLM Inference Leaves the Machine: Storage is 100% local, but LLM inference necessarily sends
profile context to the configured provider"), added Environment Overrides documentation table.
Evidence: `notes/evidence/F6-qa.md`. Tests: 4 new tests across `tests/test_config.py`
(3 env-override tests: test_env_overrides_imap_and_a2a_and_db, test_env_override_bool_true_variants,
test_env_unset_file_and_default_values_win) and `tests/test_a2a.py` (1 unknown-action test:
test_delegate_task_unknown_action_returns_400). Full suite: 49 passed (45 baseline + 4 new).
Lesson: Declaring environment variables in documentation but never reading them creates a false
sense of configurability — users set env vars expecting them to work, but the application silently
ignores them. Wire env vars explicitly with validation (log warnings on invalid values, don't
crash silently), and document the precedence order so users know which source wins.

# F6 QA Verification Report

**Task**: F6 — Dead config wiring, duplicate @tool removal, 400 contract fix, README claims
**Verifier**: QA Agent (adversarial mode)
**Date**: 2026-09-12
**Worker evidence**: notes/evidence/F6-worker.md

---

## Verification Points (independent re-verification)

### VP1: Environment overrides wired in config.py
**Status**: ✓ PASS

Executed: `timeout 300 venv/bin/python -m pytest tests/test_config.py -v`
```
tests/test_config.py::test_load_config_defaults PASSED
tests/test_config.py::test_env_overrides_imap_and_a2a_and_db PASSED
tests/test_config.py::test_env_override_bool_true_variants PASSED
tests/test_config.py::test_env_unset_file_and_default_values_win PASSED
tests/test_config.py::test_load_profile_fallback PASSED
```

Code review confirmed:
- `_parse_bool_env()` correctly handles "1", "true", "yes" (case-insensitive)
- `_collect_env_overrides()` reads IMAP_HOST/PORT/USE_SSL, A2A_HOST/PORT, JOBAGENT_DB
- Invalid int values logged as warnings and ignored (not silent failure)
- `_apply_env_overrides()` applied after config file merge (precedence: env > local > example > defaults)

### VP2: Duplicate module-level @tool functions deleted
**Status**: ✓ PASS

Executed: `grep -rn "def ingest_emails\|def archive_job_posting\|def generate_compliance_report" src/tools/`
```
exit=1 (no hits)
```

Executed: `grep -rn "name=\"ingest_emails\"\|name=\"archive_job_posting\"\|name=\"generate_compliance_report\"" src/`
```
src/agent/coordinator.py:58:        @tool(name="ingest_emails", ...)
src/agent/coordinator.py:72:        @tool(name="generate_compliance_report", ...)
src/agent/coordinator.py:91:        @tool(name="archive_job_posting", ...)
```

Only session-bound coordinator closures remain. Module-level duplicates in src/tools/email_ingest_tool.py, src/tools/job_archive_tool.py, src/tools/report_render_tool.py removed. Engine classes retained.

### VP3: Unknown A2A action returns HTTP 400
**Status**: ✓ PASS

Executed: `timeout 300 venv/bin/python -m pytest tests/test_a2a.py::test_delegate_task_unknown_action_returns_400 -v`
```
tests/test_a2a.py::test_delegate_task_unknown_action_returns_400 PASSED
```

Code review confirmed:
- server.py line 358-363: `except HTTPException: raise` placed before generic `except Exception`
- Test posts `{"action":"bogus"}` with valid auth token
- Asserts `res.status_code == 400` and `"bogus" in res.json()["detail"]`
- _make_f3_app helper exists (line 118) and provides valid test token

### VP4: .env.example no longer advertises unused keys
**Status**: ✓ PASS

Executed: `grep -n "OPENAI_API_KEY\|GMAIL_APP_PASSWORD" .env.example`
```
exit=1 (no hits)
```

IMAP_USER/IMAP_PASSWORD retained (used by adapters). New env override vars documented in .env.example with precedence note.

### VP5: README claims corrected
**Status**: ✓ PASS

Executed: `grep -n "26 unit" README.md`
```
exit=1 (no hits)
```

Replaced with version-neutral: "extensive test suite covering all core functionalities"

Executed: `grep -n "configured provider" README.md`
```
384:- **LLM Inference Leaves the Machine**: Storage is 100% local, but LLM inference (Gemini or Bedrock) necessarily sends the profile context needed for form reasoning and email classification to the configured provider. Only the data needed for the task is included; inference never stores your data on the provider side.
```

Privacy section updated with honest provider-inference disclosure. New "Environment Overrides" table added documenting all 6 env vars.

### VP6: Full test suite green
**Status**: ✓ PASS

Executed: `timeout 600 venv/bin/python -m pytest tests/ -q`
```
49 passed, 1 warning in 24.53s
```

45 baseline + 4 new tests (3 config env-override + 1 A2A unknown-action). Single warning is pre-existing starlette DeprecationWarning (anyio BlockingPortal), unrelated to F6.

---

## Scope Check
**Status**: ✓ PASS

Modified files (10):
- .env.example ✓ (F6 scope)
- README.md ✓ (F6 scope)
- notes/TASKBOARD.md ✓ (standard QA process)
- src/a2a/server.py ✓ (F6 scope)
- src/core/config.py ✓ (F6 scope)
- src/tools/email_ingest_tool.py ✓ (F6 scope)
- src/tools/job_archive_tool.py ✓ (F6 scope)
- src/tools/report_render_tool.py ✓ (F6 scope)
- tests/test_a2a.py ✓ (F6 scope)
- tests/test_config.py ✓ (F6 scope)

No unrelated changes detected.

---

## Security Spot-Check
**Status**: ✓ PASS

- No new stored secrets introduced
- .env.example removed unused OPENAI_API_KEY and GMAIL_APP_PASSWORD (good practice)
- No `except: pass` patterns found in modified files
- Error paths loud: invalid env ints logged as warnings, HTTPException properly re-raised
- No forbidden fallbacks reintroduced

Executed: `grep -n "except.*pass\b" src/a2a/server.py src/core/config.py src/tools/email_ingest_tool.py src/tools/job_archive_tool.py src/tools/report_render_tool.py`
```
exit=1 (no hits)
```

---

## Quality Check
**Status**: ✓ PASS

- Dead code removed: 3 duplicate module-level @tool functions (ingest_emails, archive_job_posting, generate_compliance_report)
- Unused imports removed: `json` from email_ingest_tool.py, `from strands import tool` from all three tool files
- No dead code added
- Test quality verified: all new tests contain real assertions, not stubs or always-pass
- _make_f3_app helper exists (test_a2a.py:118) and properly used by new test

---

## Test Code Review
**Status**: ✓ PASS

Reviewed test_config.py (lines 1-80):
- test_env_overrides_imap_and_a2a_and_db: sets 6 env vars via monkeypatch, asserts all propagate to config
- test_env_override_bool_true_variants: loops over ("1", "true", "yes", "TRUE"), asserts each parses to True
- test_env_unset_file_and_default_values_win: deletes all env vars, asserts file/default values win

Reviewed test_a2a.py (lines 220-250):
- test_delegate_task_unknown_action_returns_400: uses _make_f3_app helper, posts bogus action, asserts 400 status
- Test is not a stub, contains real HTTP request and status code assertion

---

## Verdict

All 6 verification points pass. Scope check, security spot-check, and quality check pass. No evidence of stub tests, silent failures, or scope violations.

**VERDICT: PASS**

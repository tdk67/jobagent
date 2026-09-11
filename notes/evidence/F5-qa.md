# F5 QA Verification — Data integrity: no fabricated data in statutory/compliance paths

**QA Agent:** Detached verifier (adversarial stance)  
**Date:** 2026-09-12  
**Task:** F5 (FIX_PLAN.md lines 154–192)

## Verification Protocol Executed

### VP1: New tests in tests/test_storage.py

**Test names found:**
```
109:def test_import_from_summary_unparseable_role_uses_unknown_placeholder(tmp_path: Path):
124:def test_import_from_summary_does_not_overwrite_real_role_with_placeholder(tmp_path: Path):
145:def test_import_from_summary_interviews_use_unknown_role_placeholder(tmp_path: Path):
```

**Independent test run (fresh execution):**
```
$ timeout 120 venv/bin/python -m pytest tests/test_storage.py -v
tests/test_storage.py::test_storage_crud PASSED
tests/test_storage.py::test_import_from_summary_unparseable_role_uses_unknown_placeholder PASSED
tests/test_storage.py::test_import_from_summary_does_not_overwrite_real_role_with_placeholder PASSED
tests/test_storage.py::test_import_from_summary_interviews_use_unknown_role_placeholder PASSED
4 passed in 0.32s
```

**Code review:** Tests are real, not stubs. They use meaningful assertions:
- Test 1: Verifies unparseable subject ("Rückmeldung zu Ihrer Bewerbung") → role == UNKNOWN_ROLE
- Test 2: First import gets UNKNOWN_ROLE, manual update to "Backend Engineer", second import must NOT overwrite back to UNKNOWN_ROLE (data integrity rule)
- Test 3: Interview import with unparseable role must also use UNKNOWN_ROLE (not "Senior Software Engineer")

Helper function `_write_summary_file` creates minimal test fixtures with empty job_title to force role parsing from email subject.

**Verdict: PASS** ✅

---

### VP2: No "Senior Software Engineer" in src/core/storage.py / run_agent.py

```
$ grep -n "Senior Software Engineer" src/core/storage.py run_agent.py
EXIT=1
```

Exit code 1 = no matches found.

**Verdict: PASS** ✅

---

### VP3: No "Auto-importing" / "C:/Data" in run_agent.py

```
$ grep -n "Auto-importing\|C:/Data" run_agent.py
EXIT=1
```

Exit code 1 = no matches found.

**Verdict: PASS** ✅

---

### VP4: No hardcoded "Ja"/"Nein" fabrications in extension/content.js

```
$ grep -n '"Ja"\|"Nein"' extension/content.js
EXIT=1
```

Exit code 1 = no matches found.

**Code review of diff:** The hardcoded values in `localFallbackFill` were removed:
- Work authorization: `val = "Ja"` removed, now calls `markForReview(el)` and `continue`
- Previously employed: `val = "Nein"` removed, now calls `markForReview(el)` and `continue`

The `markForReview` function (lines 349–356) sets dashed amber border + tooltip "⚠️ Legally significant question — please answer manually". Used at lines 441, 448 (legal questions) and 469, 477 (salary/notice confirm-marking).

**Verdict: PASS** ✅

---

### VP5: `run_agent.py --import-summary` without value exits non-zero

```
$ timeout 30 venv/bin/python run_agent.py --import-summary
usage: run_agent.py [-h] [--demo] [--cycle] [--server] [--mcp] [--port PORT]
                    [--host HOST] [--db DB] [--reset-db]
                    [--report {all,afa_table,dashboard,agency_summary}]
                    [--start-date START_DATE] [--end-date END_DATE] [--weekly]
                    [--triage] [--import-summary [IMPORT_SUMMARY]]
                    [--cover-letter] [--company COMPANY] [--role ROLE]
                    [--lang {de,en}]
run_agent.py: error: --import-summary requires a path
EXIT_CODE=2
```

Exit code 2 (argparse error), usage message printed, DB construction never reached.

**Code review:** argparse configured with `const=None, default=argparse.SUPPRESS`, then explicit check:
```python
elif hasattr(args, "import_summary"):
    if args.import_summary is None:
        parser.error("--import-summary requires a path")
```

**Verdict: PASS** ✅

---

### VP6: Full test suite green

```
$ timeout 600 venv/bin/python -m pytest tests/ -v
...
45 passed, 1 warning in 26.42s
```

45 tests passed (42 baseline + 3 new F5 tests). 1 pre-existing DeprecationWarning from starlette's testclient (anyio alias, unrelated to F5).

**Verdict: PASS** ✅

---

## Scope Check

```
$ git status --short
 M extension/content.js
 M notes/TASKBOARD.md
 M run_agent.py
 M src/core/storage.py
 M tests/test_storage.py
?? notes/evidence/F5-worker.md
```

Only F5-related files modified:
- `src/core/storage.py` — UNKNOWN_ROLE constant, unparseable role handling, non-overwrite logic
- `run_agent.py` — removed auto-import magic, fixed --import-summary validation
- `extension/content.js` — markForReview function, removed hardcoded Ja/Nein, confirm-marking
- `tests/test_storage.py` — 3 new tests for F5
- `notes/TASKBOARD.md` — status update (expected)
- `notes/evidence/F5-worker.md` — worker evidence (expected, untracked)

No unrelated changes detected.

**Verdict: PASS** ✅

---

## Security Spot-Check

**No new stored secrets:** Diff review shows no new API keys, tokens, or credentials introduced.

**No forbidden fallbacks reintroduced:** The changes actively remove dangerous defaults:
- Removed `"Senior Software Engineer"` fabrication (compliance risk in statutory reports)
- Removed `"Ja"/"Nein"` fabrications (legal risk for work authorization/employment questions)
- Removed hardcoded `C:/Data/work/jobSearch/...` path (no silent auto-import)

**Error paths are loud:**
- `run_agent.py --import-summary` (no value) → exit 2 with clear error message
- `parser.error()` is explicit and loud

**No silent except:pass:** The `markForReview` function in content.js has a try/catch, but it's acceptable for non-critical UI decoration code. Failures here don't mask real errors.

**Verdict: PASS** ✅

---

## Quality Check

**No dead code added:** All new code serves a clear purpose:
- `UNKNOWN_ROLE` constant used in both application and interview import branches
- `_NON_ROLE_SUBJECT_MARKERS` list prevents false matches on sales-spam subjects
- `markForReview` function reused for all legally significant questions

**Data integrity enforced:**
- Existing real roles are never overwritten with placeholder (test 2 verifies this)
- Regex tightened to require explicit "Position:" with colon (prevents "Keine Position erkennbar" false match)
- Sales-spam subjects excluded before regex attempt

**Verdict: PASS** ✅

---

## Independent Implementation Verification

**storage.py changes:**
- `UNKNOWN_ROLE = "Unbekannt (bitte prüfen)"` defined at module level (line 24)
- `_NON_ROLE_SUBJECT_MARKERS` list excludes deceptive sales pitches (line 27)
- Application import: checks existing role before overwriting, uses UNKNOWN_ROLE only when no real role exists (lines 700–732)
- Interview import: uses UNKNOWN_ROLE instead of "Senior Software Engineer" (lines 775–782)
- Regex tightened to require "Position:" with colon (line 719)

**run_agent.py changes:**
- `--import-summary`: `const=None, default=argparse.SUPPRESS` (line 163)
- Explicit validation: `if args.import_summary is None: parser.error(...)` (line 192)
- Removed auto-import magic block from `--report` path (lines 205–209)
- `--role` default changed to `None` (line 170), cover letter uses "Software Engineer" neutral fallback

**extension/content.js changes:**
- `markForReview(el)` function sets dashed amber border + tooltip (lines 349–356)
- Work authorization: removed `val = "Ja"`, now empty + marked (lines 441–443)
- Previously employed: removed `val = "Nein"`, now empty + marked (lines 448–450)
- Salary/notice: autofill from profile but marked for confirmation (lines 469, 477)
- Console log reports count of legally significant questions left empty (line 500)

**Verdict: PASS** ✅

---

## Summary

All 6 verification points passed independently. Code review confirms the implementation matches the FIX_PLAN requirements. No security issues, no quality concerns, no scope violations.

The worker's claims are **VERIFIED**:
1. ✅ Unparseable roles default to "Unbekannt (bitte prüfen)" (not fabricated titles)
2. ✅ Existing real roles are protected from overwrite
3. ✅ Auto-import magic removed, explicit validation enforced
4. ✅ Legally significant questions left empty and marked for human review
5. ✅ All tests pass, no regressions

**VERDICT: PASS**

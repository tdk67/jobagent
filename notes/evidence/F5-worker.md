# F5 worker evidence — Data integrity: no fabricated data in statutory/compliance paths

Date: 2026-09-12 · Repo: /root/jobagent · Task: F5 (FIX_PLAN.md lines 154–192)

## Scope implemented (files touched)

- `src/core/storage.py` — `UNKNOWN_ROLE = "Unbekannt (bitte prüfen)"`; unparseable roles
  in `import_from_summary` (applications AND interviews branches) now use the placeholder
  instead of the fabricated "Senior Software Engineer". An existing application with a
  real role is never clobbered by the placeholder on a second import pass. Regex tightened
  so bare "Position" without a colon (e.g. "Keine Position erkennbar") cannot falsely parse;
  sales-spam subjects (webinar/netzwerk/coaching/etc.) are excluded from the role-parsing
  fallback before the regex is even attempted.
- `run_agent.py` — removed the hidden auto-import magic block
  (`if len(existing_apps) <= 2 and default_sum.exists() ...`) and the hardcoded
  `C:/Data/work/jobSearch/...` default from the `--import-summary` const. `const=None` +
  `default=argparse.SUPPRESS`: flag without value → `parser.error` (exit 2, message
  "--import-summary requires a path"). Also removed the fabricated `--role` default for
  cover letters (now `None`; CoverLetterEngine fills "Software Engineer" neutral fallback).
- `extension/content.js` — `localFallbackFill`: work-authorization and previously-employed
  questions are no longer hardcoded `val = "Ja"` / `val = "Nein"`; they are left EMPTY and
  marked via `markForReview(el)` (2px dashed amber border + title "⚠️ Legally significant
  question — please answer manually"). Salary/notice-period autofills from the profile get
  the same confirm-marking.
- `tests/test_storage.py` — 3 new tests added.

## Verification point 1 — New tests in tests/test_storage.py

Test names:

```
109:def test_import_from_summary_unparseable_role_uses_unknown_placeholder(tmp_path: Path):
124:def test_import_from_summary_does_not_overwrite_real_role_with_placeholder(tmp_path: Path):
145:def test_import_from_summary_interviews_use_unknown_role_placeholder(tmp_path: Path):
```

Verification-first: before implementation the module failed to collect
(ImportError: cannot import name 'UNKNOWN_ROLE'), and afterward the second test
exposed the regex over-match ("erkennbar" parsed from "Keine Position erkennbar"),
which was fixed before proceeding.

Real output of the storage test file after implementation:

```
$ timeout 120 venv/bin/python -m pytest tests/test_storage.py -q
....                                                                     [100%]
4 passed in 0.31s
```

Manual behavior probe (unparseable, parseable via "als", and sales-spam subject):

```
$ python3 - <<EOF ... EOF
'Acme GmbH'      -> 'Senior Python Engineer'
'Herr Muster'    -> 'Unbekannt (bitte prüfen)'
'Sales Webinar'  -> 'Unbekannt (bitte prüfen)'
EOF
```

## Verification point 2 — no "Senior Software Engineer" in src/core/storage.py / run_agent.py

```
$ grep -n "Senior Software Engineer" src/core/storage.py run_agent.py
(no output, exit=1)
```

## Verification point 3 — no "Auto-importing" / "C:/Data" in run_agent.py

```
$ grep -n "Auto-importing\|C:/Data" run_agent.py
(no output, exit=1)
```

## Verification point 4 — no hardcoded "Ja"/"Nein" fabrications in extension/content.js

```
$ grep -n '"Ja"\|"Nein"' extension/content.js
(no output, exit=1)
```

Syntax check:

```
$ node --check extension/content.js
SYNTAX OK
```

markForReview markers present at content.js:349 (helper), used at lines 441/448
(legal questions), 469/477 (salary/notice confirm-marking).

## Verification point 5 — `run_agent.py --import-summary` without value

```
$ timeout 30 venv/bin/python run_agent.py --import-summary
usage: run_agent.py ... 
run_agent.py: error: --import-summary requires a path
$ echo $?
2
```

Exit 2 (non-zero), usage message printed, DB untouched (error fires before any storage
construction). With a path: existing behavior preserved
(`--import-summary /nonexistent/summary.json` → FileNotFoundError, exit 1 — did not hang).

## Verification point 6 — full test suite

```
$ timeout 600 venv/bin/python -m pytest tests/ -q
.............................................                            [100%]
45 passed, 1 warning in 26.34s
```

45 passed (42 baseline + 3 new F5 tests), 1 pre-existing DeprecationWarning
(anyio alias in starlette's testclient — unrelated, present at baseline).

## Extra sanity checks

- `timeout 240 venv/bin/python run_agent.py --demo` → exit 0, interview detected,
  meeting link printed (demo path unaffected).
- `venv/bin/python -c "import run_agent"` → OK (CLI module still importable).
- `git status --short` → only the 4 F5 files modified; no commits made (QA gates commits).
- No secrets/PII introduced; all fixtures use dummy data.
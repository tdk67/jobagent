# F4 QA Verification — 2026-09-12

**Task**: Correctness: city bug, IMAP dates, dead LLM fallback, Gmail no-op, model fail-loud  
**Worker evidence**: notes/evidence/F4-worker.md  
**QA verifier**: Independent adversarial verification

---

## VP1 — City bug (reasoner + content.js)

**Worker claim**: Fixed `pers.address.split(",")[0]` (street) → `pers.city` with fallback to postal-code segment.

**QA verification**:
```bash
$ timeout 60 venv/bin/python -m pytest tests/test_form_reasoner.py::test_form_reasoner_city_field_maps_to_city_not_street tests/test_form_reasoner.py::test_form_reasoner_city_falls_back_to_postal_segment -v
tests/test_form_reasoner.py::test_form_reasoner_city_field_maps_to_city_not_street PASSED
tests/test_form_reasoner.py::test_form_reasoner_city_falls_back_to_postal_segment PASSED
```

**Source inspection**:
- `src/tools/form/reasoner.py:78` now uses `pers.city or self._extract_city_from_address(pers.address)`
- Helper `_extract_city_from_address` finds segment with postal code, strips it, never uses segment 0
- `extension/content.js:441` now uses `pers.city || ((pers.address || "").split(",")[1] || "").replace(/^\s*\d{4,5}\s*/, "").trim() || ""`

**Test quality**: Tests assert specific city values ("Frankfurt am Main"), not just non-empty. Tests verify street is NOT returned. Genuine assertions. ✓

**VP1: PASS**

---

## VP2 — IMAP date range (SINCE / BEFORE criteria)

**Worker claim**: Added `build_imap_search_criteria(start_date, end_date, cutoff_date)` helper, wired into ImapAdapter.

**QA verification**:
```bash
$ timeout 60 venv/bin/python -m pytest tests/test_email_ingest.py::test_build_imap_search_criteria_start_end tests/test_email_ingest.py::test_build_imap_search_criteria_none_none tests/test_email_ingest.py::test_build_imap_search_criteria_cutoff_only tests/test_email_ingest.py::test_build_imap_search_criteria_flexible_inputs -v
tests/test_email_ingest.py::test_build_imap_search_criteria_start_end PASSED
tests/test_email_ingest.py::test_build_imap_search_criteria_none_none PASSED
tests/test_email_ingest.py::test_build_imap_search_criteria_cutoff_only PASSED
tests/test_email_ingest.py::test_build_imap_search_criteria_flexible_inputs PASSED
```

**Source inspection**:
- `src/tools/email/adapters.py:27-87` adds `_parse_flexible_iso`, `_to_imap_date`, `build_imap_search_criteria`
- `src/tools/email/adapters.py:319` calls `server.search(build_imap_search_criteria(start_date, end_date, cutoff_date), "ALL")` (was `server.search(None, "ALL")`)
- Tests verify: start+end → `["SINCE 01-Sep-2026", "BEFORE 08-Sep-2026"]`, None/None → `["ALL"]`, cutoff → `["SINCE 15-Aug-2026"]`

**Test quality**: Tests assert exact IMAP criteria strings. Tests cover flexible input formats (datetime objects, human-friendly strings). Genuine assertions. ✓

**VP2: PASS**

---

## VP3 — Dead LLM triage fallback wired

**Worker claim**: Added `llm_fallback: bool = False` to config, wired through `EmailIngestEngine.run_triage`.

**QA verification**:
```bash
$ timeout 60 venv/bin/python -m pytest tests/test_email_ingest.py::test_run_triage_passes_llm_fallback_flag tests/test_email_ingest.py::test_run_triage_llm_fallback_false_by_default -v
tests/test_email_ingest.py::test_run_triage_passes_llm_fallback_flag PASSED
tests/test_email_ingest.py::test_run_triage_llm_fallback_false_by_default PASSED
```

**Source inspection**:
- `src/core/config.py:80` adds `llm_fallback: bool = False` to `EmailIngestionConfig`
- `config.example.json:48` documents `"llm_fallback": false`
- `src/tools/email_ingest_tool.py:127` passes `enable_llm_fallback=self.config.email_ingestion.llm_fallback` to `classifier.classify(...)`

**Test quality**: Tests monkeypatch `EmailClassifier.classify` to capture kwargs, then assert `enable_llm_fallback` was passed correctly. Genuine assertions. ✓

**VP3: PASS**

---

## VP4 — Strands model fail-loud (llm_available gating)

**Worker claim**: Added `self.llm_available` computed in `_init_strands_agent`, gates agent-reasoning branch.

**QA verification**:
```bash
$ timeout 60 venv/bin/python -m pytest tests/test_autonomous_agent.py::test_coordinator_no_provider_creds_llm_unavailable tests/test_autonomous_agent.py::test_coordinator_deterministic_cycle_fallback tests/test_autonomous_agent.py::test_coordinator_multi_cycle_idempotency -v
tests/test_autonomous_agent.py::test_coordinator_deterministic_cycle_fallback PASSED
tests/test_autonomous_agent.py::test_coordinator_multi_cycle_idempotency PASSED
tests/test_autonomous_agent.py::test_coordinator_no_provider_creds_llm_unavailable PASSED
```

**Source inspection**:
- `src/agent/coordinator.py:133` initializes `llm_available = False`
- Lines 139, 163 set `llm_available = True` only when Gemini or Bedrock successfully initialize with credentials
- Line 169 sets `self.llm_available = llm_available`
- Line 170 logs warning if False: `"No LLM provider configured (set GEMINI_API_KEY or AWS credentials) — running deterministic tool-only mode"`
- Line 195 gates agent call: `if self.llm_available and self.agent and getattr(self.agent, "model", None):`

**Test quality**: Test `test_coordinator_no_provider_creds_llm_unavailable` uses ExplodingAgent pattern — if the gating logic were wrong and the agent were called, the test would raise. Genuine assertions. ✓

**VP4: PASS**

---

## VP5 — Gmail adapter silent no-op fixed

**Worker claim**: Dead `GmailMcpAdapter(mcp_client=None)` no longer appended; loud warning logged instead.

**QA verification**:
```bash
$ grep -n "mcp_client=None" src/tools/email_ingest_tool.py
exit=1
```
(No hits — the dead construction is gone.)

```bash
$ timeout 60 venv/bin/python -m pytest tests/test_email_ingest.py::test_gmail_dead_adapter_not_appended -v
tests/test_email_ingest.py::test_gmail_dead_adapter_not_appended PASSED
```

**Source inspection**:
- `src/tools/email_ingest_tool.py:48-65` tries to import `get_mcp_client`, catches exception, sets `mcp_client = None`
- Line 57 logs `log.warning("Gmail ingestion enabled in config but no MCP client is wired — adapter will fetch nothing")`
- Line 62 only appends the adapter if `mcp_client is not None`

**Test quality**: Test asserts both the empty adapter list AND the presence of the loud warning. Genuine assertions. ✓

**VP5: PASS**

---

## VP6 — Full test suite green

```bash
$ timeout 600 venv/bin/python -m pytest tests/ -q
42 passed, 1 warning in 27.73s
```

**Baseline**: 32 tests (per TASKBOARD.md after F3)  
**F4 additions**: 10 tests (2 VP1 + 4 VP2 + 2 VP3 + 1 VP4 + 1 VP5)  
**Result**: 42 passed, 0 failures, 0 errors ✓

**VP6: PASS**

---

## Scope check

```bash
$ git diff --cached --name-only | grep -v "^notes/" | sort
config.example.json
extension/content.js
src/agent/coordinator.py
src/core/config.py
src/tools/email/adapters.py
src/tools/email_ingest_tool.py
src/tools/form/reasoner.py
tests/test_autonomous_agent.py
tests/test_email_ingest.py
tests/test_form_reasoner.py
```

All files are listed in FIX_PLAN.md F4 scope. No unrelated changes. ✓

---

## Security spot-check

```bash
$ grep -rn "sk-[A-Za-z0-9]\{20,\}\|AKIA[0-9A-Z]\{16\}\|ghp_[A-Za-z0-9]\{20,\}" src/ config.example.json extension/
exit=1
```
(No hardcoded secrets found.)

---

## Quality check

```bash
$ git diff --cached src/ | grep -B2 -A2 "except:" | head -30
(no output)

$ git diff --cached src/ | grep -B1 "pass$" | head -20
(no output)
```

- No silent `except: pass` patterns added
- Error paths are loud: `log.warning` for Gmail dead adapter (line 57), `log.warning` for no LLM provider (line 170)
- No dead code added
- Tests have meaningful assertions (not just `assert True`)

✓

---

## VERDICT

All 6 verification points pass. Tests are genuine with real assertions. Source code changes match the plan. No scope creep. No security issues. Error paths are loud.

VERDICT: PASS

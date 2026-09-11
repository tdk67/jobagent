# F4 — Correctness: city bug, IMAP dates, dead LLM fallback, Gmail no-op, model fail-loud

**Worker evidence — 2026-09-12.** All FIX_PLAN.md F4 verification points (1–6) pass.
No PII introduced (all fixtures dummy). No commits made (QA gates commits).

---

## VP1 — City bug (reasoner maps "City"/"Ort"/"Stadt" to the city, not the street)

Fix in `src/tools/form/reasoner.py`:
- `_match_core_profile` city branch now returns `pers.city`, else falls back to
  `self._extract_city_from_address(pers.address)` — a new helper that picks the
  address segment containing the postal code (stripped of the leading postal code),
  NEVER segment 0 (the street).
- `extension/content.js` `localFallbackFill` city branch: `pers.city` with fallback
  `pers.address.split(",")[1]` trimmed of a leading postal code (was `split(",")[0]`).

New tests in `tests/test_form_reasoner.py`:

```
$ timeout 600 venv/bin/python -m pytest tests/test_form_reasoner.py::test_form_reasoner_city_field_maps_to_city_not_street tests/test_form_reasoner.py::test_form_reasoner_city_falls_back_to_postal_segment -v 2>&1 | grep -E "PASSED|FAILED|ERROR"
tests/test_form_reasoner.py::test_form_reasoner_city_field_maps_to_city_not_street PASSED
tests/test_form_reasoner.py::test_form_reasoner_city_falls_back_to_postal_segment PASSED
```

VP1 checks: label "City" / "Ort" / "Stadt" / "Wohnort" all mapped to
"Frankfurt am Main" while `pers.address = "Musterstrasse 1, 60311 Frankfurt am Main, Deutschland"`
(assertion that the street segment was NOT used), plus the no-`pers.city` fallback to the
postal-code segment. Fix confirmed in source:

```
$ sed -n '78,105p' src/tools/form/reasoner.py
        # 6. City / Address
        if any(term in combined for term in ["city", "ort", "stadt", "wohnort", "location", "standort"]):
            city = pers.city or self._extract_city_from_address(pers.address)
            return {"value": city, "confidence": 1.0, "reasoning": "Core profile city"}
        ...
    def _extract_city_from_address(self, address: Optional[str]) -> str:
        ...
        postal = re.search(r"\b\d{4,5}\b", address)
        for seg in segments:
            if postal and postal.group(0) in seg:
                candidate = re.sub(r"^\s*\d{4,5}\s*", "", seg).strip()
                return candidate or seg
        # No postal code: the last segment is the city for 'Street, City' layouts
        return segments[-1]
```

```
$ grep -n "split(\",\")" extension/content.js
441:        val = pers.city || ((pers.address || "").split(",")[1] || "").replace(/^\s*\d{4,5}\s*/, "").trim() || "";
```

---

## VP2 — IMAP date range (SINCE / BEFORE criteria)

Fix in `src/tools/email/adapters.py`: added module-level pure helpers
`_parse_flexible_iso`, `_to_imap_date`, and `build_imap_search_criteria(start_date, end_date, cutoff_date)`.
`ImapAdapter.fetch_emails` now calls
`server.search(build_imap_search_criteria(start_date, end_date, cutoff_date), "ALL")`
(was `server.search(None, "ALL")`). The client-side `cutoff_date` filter remains as a second guard.

New tests in `tests/test_email_ingest.py` (4 tests, no live IMAP):

```
$ timeout 600 venv/bin/python -m pytest tests/test_email_ingest.py::test_build_imap_search_criteria_start_end tests/test_email_ingest.py::test_build_imap_search_criteria_none_none tests/test_email_ingest.py::test_build_imap_search_criteria_cutoff_only tests/test_email_ingest.py::test_build_imap_search_criteria_flexible_inputs -v 2>&1 | grep -E "PASSED|FAILED|ERROR"
tests/test_email_ingest.py::test_build_imap_search_criteria_start_end PASSED
tests/test_email_ingest.py::test_build_imap_search_criteria_none_none PASSED
tests/test_email_ingest.py::test_build_imap_search_criteria_cutoff_only PASSED
tests/test_email_ingest.py::test_build_imap_search_criteria_flexible_inputs PASSED
```

Covered cases: start+end → `["SINCE 01-Sep-2026", "BEFORE 08-Sep-2026"]`;
None/None → `["ALL"]`; cutoff only → `["SINCE 15-Aug-2026"]`; flexible input formats
("1-Sep-2026", tz-aware datetime) → same criteria.

---

## VP3 — Dead LLM triage fallback wired

Fixes:
- `src/core/config.py`: `EmailIngestionConfig` gained `llm_fallback: bool = False`.
- `config.example.json`: documented the new flag under `email_ingestion` (`"llm_fallback": false`).
- `src/tools/email_ingest_tool.py` `EmailIngestEngine.run_triage` now passes
  `enable_llm_fallback=self.config.email_ingestion.llm_fallback` into `classifier.classify(...)`
  (was never passed → always default False → dead fallback).

New tests in `tests/test_email_ingest.py` (monkeypatch `EmailClassifier.classify` to capture kwargs):

```
$ timeout 600 venv/bin/python -m pytest tests/test_email_ingest.py::test_run_triage_passes_llm_fallback_flag tests/test_email_ingest.py::test_run_triage_llm_fallback_false_by_default -v 2>&1 | grep -E "PASSED|FAILED|ERROR"
tests/test_email_ingest.py::test_run_triage_passes_llm_fallback_flag PASSED
tests/test_email_ingest.py::test_run_triage_llm_fallback_false_by_default PASSED
```

Config docs verified:

```
$ grep -n "llm_fallback" config.example.json src/core/config.py
config.example.json:48:    "llm_fallback": false
src/core/config.py:80:    llm_fallback: bool = False
```

---

## VP4 — Strands model fail-loud (llm_available gating)

Fixes in `src/agent/coordinator.py`:
- `_init_strands_agent` now computes `self.llm_available: bool` — True ONLY if a provider was
  explicitly initialized with credentials (Gemini via `GEMINI_API_KEY`, or Bedrock via
  `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`). When False, logs ONE loud warning:
  `"No LLM provider configured (set GEMINI_API_KEY or AWS credentials) — running deterministic tool-only mode"`.
- `run_autonomous_cycle` gates the agent-reasoning branch on
  `self.llm_available and self.agent and getattr(self.agent, "model", None)`
  (was only the always-truthy model check → doomed LLM call every cycle without creds).

New/updated tests in `tests/test_autonomous_agent.py`:
- `test_coordinator_deterministic_cycle_fallback` and `test_coordinator_multi_cycle_idempotency`
  now set `coordinator.llm_available = False` (was `agent.model = None`).
- NEW `test_coordinator_no_provider_creds_llm_unavailable`: with `GEMINI_API_KEY` and AWS creds
  unset (monkeypatch), `llm_available is False`; `run_autonomous_cycle` completes via the
  deterministic path with `coordinator.agent` replaced by a Mock that RAISES if called
  (proves no agent LLM call is attempted); triage still processed 1 email (confirmation).

```
$ timeout 600 venv/bin/python -m pytest tests/test_autonomous_agent.py::test_coordinator_no_provider_creds_llm_unavailable tests/test_autonomous_agent.py::test_coordinator_deterministic_cycle_fallback tests/test_autonomous_agent.py::test_coordinator_multi_cycle_idempotency tests/test_autonomous_agent.py::test_coordinator_agent_initialization tests/test_autonomous_agent.py::test_coordinator_tools_session_binding -v 2>&1 | grep -E "PASSED|FAILED|ERROR"
tests/test_autonomous_agent.py::test_coordinator_agent_initialization PASSED
tests/test_autonomous_agent.py::test_coordinator_tools_session_binding PASSED
tests/test_autonomous_agent.py::test_coordinator_deterministic_cycle_fallback PASSED
tests/test_autonomous_agent.py::test_coordinator_multi_cycle_idempotency PASSED
tests/test_autonomous_agent.py::test_coordinator_no_provider_creds_llm_unavailable PASSED
```

---

## VP5 — Gmail adapter silent no-op fixed

Fix in `src/tools/email_ingest_tool.py` `EmailIngestEngine.__init__`: when `gmail.enabled`
but no MCP client can be constructed (nothing in the repo provides one — `src/mcp/` does not
exist, so the guarded import fails), the engine logs ONCE:
`"Gmail ingestion enabled in config but no MCP client is wired — adapter will fetch nothing"`
and does NOT append a dead `GmailMcpAdapter` to `self.adapters`.

Verification (VP5):

```
$ grep -n "mcp_client=None" src/tools/email_ingest_tool.py; echo "exit=$?"
exit=1
```

(no hits — the `mcp_client=None` construction is gone).

New test `test_gmail_dead_adapter_not_appended` in `tests/test_email_ingest.py`:

```
$ timeout 600 venv/bin/python -m pytest tests/test_email_ingest.py::test_gmail_dead_adapter_not_appended -v 2>&1 | grep -E "PASSED|FAILED|ERROR"
tests/test_email_ingest.py::test_gmail_dead_adapter_not_appended PASSED
```

(sets `gmail.enabled=True`, `outlook_desktop.enabled=False`, no MCP factory available →
`engine.adapters == []` and the loud `log.warning` was captured).

---

## VP6 — Full test suite green

```
$ timeout 600 venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
42 passed, 1 warning in 31.57s
```

Result: **42 passed** (32 baseline + 10 new F4 tests), 0 failures, 0 errors.

---

## Files touched (task scope only)

- `src/tools/form/reasoner.py` — city branch + `_extract_city_from_address` helper
- `extension/content.js` — `localFallbackFill` city branch (line 441)
- `src/tools/email/adapters.py` — `build_imap_search_criteria` + SINCE/BEFORE wiring
- `src/core/config.py` — `EmailIngestionConfig.llm_fallback`
- `config.example.json` — `llm_fallback` documented
- `src/tools/email_ingest_tool.py` — run_triage passes llm_fallback; Gmail dead-adapter guard
- `src/agent/coordinator.py` — `llm_available` + fail-loud gating
- `tests/test_autonomous_agent.py` — updated fallback tests + new no-creds test
- `tests/test_form_reasoner.py` — 2 new VP1 city tests
- `tests/test_email_ingest.py` — 4 VP2 criteria tests + 2 VP3 llm_fallback tests + 1 VP5 Gmail test

No deviations from plan scope. No commits/pushes made.
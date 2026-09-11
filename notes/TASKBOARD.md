# JobAgent TASKBOARD — remediation loop (see notes/FIX_PLAN.md)

| Task | Scope | Status | Note |
|------|-------|--------|------|
| F1 | PII purge: sanitize test fixture + squash history + force-push | **done** | commit `04e93ae`, remote history verified CLEAN via fresh clone (2026-09-12, done by lead agent, not via loop) |
| F2 | Extension message-channel security (postMessage token/PII broadcast, unorigin-checked listener) | **done** | commit `4f6a0d6` [QA: PASS] — broadcast block + window listener deleted, apiToken removed from content payload, runtime-message path intact, 27 tests green |
| F3 | Gateway auth hardening (Host validation vs DNS rebinding, pair endpoint logging, Docker loopback bind) | **done** | commit `78d425f` [QA: PASS] — Host-header guard on all /api/* + /a2a/* (403 invalid Host), pair logs loopback client, Dockerfile/compose bind 127.0.0.1, run_agent env overrides A2A_HOST/A2A_PORT (CLI>env>cfg); 32 tests green |
| F4 | Correctness: city bug, IMAP date range, dead LLM fallback, Gmail no-op, Strands model fail-loud | todo | |
| F5 | Data integrity: no fabricated roles in AfA import path, remove auto-import magic, gate legal autofills | todo | |
| F6 | Dead config wiring, duplicate @tool removal, 400 contract fix, README claims | todo | |
| F7 | Final regression & judge-readiness sweep (evidence only) | todo | |

Sequencing: strictly F2 → F3 → F4 → F5 → F6 → F7 (worker → QA gates commit+push → next).

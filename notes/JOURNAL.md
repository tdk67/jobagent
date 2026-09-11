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

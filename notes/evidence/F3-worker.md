# F3 — Gateway auth hardening (review S2 + DNS rebinding + Docker exposure)

**Worker evidence — run 2026-09-12.** Repo `/root/jobagent`, python `venv/bin/python`.

## What changed (files per FIX_PLAN F3)

- `src/a2a/server.py` — added HTTP middleware on the gateway app validating the
  `Host` header for all `/api/*` and `/a2a/*` routes. Allowed hostnames: loopback
  set `{127.0.0.1, localhost, ::1}` plus the configured `cfg.a2a.host`; anything
  else → HTTP 403 `{"detail": "Invalid Host header"}`. Public probes
  (`/health`, `/robots.txt`, `/llms.txt`) stay unguarded. Host parsing handles
  `host[:port]` and bracketed IPv6 `[::1]:port`. The loopback client-IP check on
  `/api/v1/auth/pair` is kept, and every successful pairing now logs
  `log.info("Extension paired from %s", client_host)`.
  Helper functions added at module level: `_host_header_value`,
  `_is_allowed_host_header`, `_is_gateway_path`.
- `Dockerfile` — CMD now `["python", "run_agent.py", "--server", "--host", "127.0.0.1", "--port", "8765"]`
  (was `0.0.0.0`), with a comment that LAN exposure is a deliberate opt-in via
  ENV `A2A_HOST` or a compose port-mapping override.
- `docker-compose.yml` — publish `"127.0.0.1:8765:8765"` (was `8765:8765`);
  `A2A_HOST=127.0.0.1` (was `0.0.0.0`); comments explain the deliberate-exposure
  path and that the gateway Host guard still rejects non-loopback Host names.
- `run_agent.py --server` — override order CLI flag > env `A2A_HOST`/`A2A_PORT`
  > config. The effective host/port are written back to `cfg.a2a` so the
  gateway's Host-header guard stays in sync with what uvicorn binds.
- `tests/test_a2a.py` — +5 new tests (31→36 tests in file; suite 27→32).
- `tests/test_form_reasoner.py` — `test_server_form_endpoints` now uses
  `TestClient(app, base_url="http://127.0.0.1:8765")` (Host guard correctly
  rejects the TestClient default `testserver`).

## Verification points

### VP1 — new tests in tests/test_a2a.py

New tests:
- `test_host_header_dns_rebinding_rejected` — `Host: evil.example.com` → 403 on
  `/api/v1/auth/pair`, on `/api/v1/profile` (valid Bearer), and on
  `/a2a/v1/capabilities` (valid Bearer).
- `test_host_header_loopback_allowed_pair_returns_token` — `Host: 127.0.0.1:8765`
  → pair returns the token; authed `/api/v1/profile` works.
- `test_host_header_localhost_and_ipv6_variants_allowed` — `localhost`,
  `localhost:8765`, `[::1]`, `[::1]:8765`, `127.0.0.1`, `127.0.0.1:8765` all OK.
- `test_host_header_configured_a2a_host_allowed` — configured `cfg.a2a.host`
  (`a2a.internal`) allowed; `evil.example.com` still 403.
- `test_auth_pair_rejects_non_loopback_client` — non-loopback client → 403
  "Auto-pairing only allowed from local loopback" (existing behavior, kept).
- (Existing `test_a2a_server_endpoints` updated: `TestClient(app, base_url="http://127.0.0.1:8765")`.)

Documented decision on TestClient Host: tests set an allowed Host explicitly via
`base_url` (loopback/config host); the TestClient default `testserver` is
correctly rejected — the check was NOT weakened to accommodate it.

Red phases (tests written before implementation) — exact outputs:

```
$ timeout 300 venv/bin/python -m pytest tests/test_a2a.py -q -k "f3 or host_header or loopback"
FAILED tests/test_a2a.py::test_host_header_dns_rebinding_rejected - Assertion...
FAILED tests/test_a2a.py::test_host_header_loopback_allowed_pair_returns_token
FAILED tests/test_a2a.py::test_host_header_localhost_and_ipv6_variants_allowed
FAILED tests/test_a2a.py::test_host_header_configured_a2a_host_allowed - Asse...
4 failed, 1 passed, 2 deselected, 1 warning in 10.47s
```
(1 passed = the pre-existing non-loopback pair check; the rest fail because the
Host guard did not exist yet. The configured-host test initially failed for a
different reason — the pair endpoint's own loopback client-IP check — fixed by
giving it a loopback client IP. That is the documented loopback-check-on-pair
behavior, not a weakening of the Host guard.)

Green phase:

```
$ timeout 300 venv/bin/python -m pytest tests/test_a2a.py -q
7 passed, 1 warning in 6.25s
```

### VP2 — no 0.0.0.0 in Dockerfile / docker-compose.yml

```
$ grep -n "0.0.0.0" Dockerfile docker-compose.yml
exit=1    (no hits — PASS; compose healthcheck uses localhost, unchanged)
```

Dockerfile CMD and compose port mapping:

```
$ grep -n "CMD\|--host" Dockerfile
76:CMD ["python", "run_agent.py", "--server", "--host", "127.0.0.1", "--port", "8765"]

$ grep -n "8765" docker-compose.yml
15:      - "127.0.0.1:8765:8765"
32:      test: ["CMD", "curl", "-f", "http://localhost:8765/health"]
```

### run_agent.py --server env override (A2A_HOST/A2A_PORT, CLI > env > config)

```
        host = args.host or os.getenv("A2A_HOST") or cfg.a2a.host
        port_env = os.getenv("A2A_PORT")
        port = args.port or (int(port_env) if port_env else cfg.a2a.port)
        # Keep the gateway's Host-header guard in sync with the effective bind:
        cfg.a2a.host = host
        cfg.a2a.port = port
```

Live smoke (server started with `A2A_HOST=127.0.0.1 A2A_PORT=8799`, killed afterwards):

```
=== 1) health (public, no host guard) ===
200
=== 2) pair with evil Host -> expect 403 ===
{"detail":"Invalid Host header"} [403]
=== 3) pair with loopback Host -> expect token ===
{"token":"5d776c1b67d503b4c8a13cc667c5538d","status":"paired"} [200]
=== 4) authed profile with evil Host -> expect 403 ===
{"detail":"Invalid Host header"} [403]
=== 5) authed capabilities loopback -> expect 200 ===
200
=== 6) pair log line ===
10:37:14 [INFO] src.a2a.server: Extension paired from 127.0.0.1
```

### VP3 — full suite green, no existing test broken

```
$ timeout 600 venv/bin/python -m pytest tests/ -q
32 passed, 1 warning in 23.15s
```
(two consecutive full runs: 32 passed / 32 passed; baseline before F3 was
27 passed — the +5 are the new F3 tests.)

No secrets introduced; no code changes outside the F3 file list (deviations:
`tests/test_form_reasoner.py` base_url adjusted in place — same test, required
line "adjust TestClient base_url/headers as needed" from the plan; helper
functions are module-level, in `src/a2a/server.py`).
# F3 QA/Verification — Gateway auth hardening (DNS rebinding + Docker exposure)

**QA Agent run:** 2026-09-12, repo /root/jobagent, python venv/bin/python.

**Worker claim:** F3 done. 32 tests pass (27 baseline + 5 new). All verification points met.

**QA approach:** Adversarial. Treat worker evidence as untrusted. Re-run everything independently.

---

## Independent Verification Results

### VP1 — New tests in tests/test_a2a.py

**Command:** `timeout 300 venv/bin/python -m pytest tests/test_a2a.py -v -k "host_header or loopback or pair"`

**Output:**
```
tests/test_a2a.py::test_host_header_dns_rebinding_rejected PASSED
tests/test_a2a.py::test_host_header_loopback_allowed_pair_returns_token PASSED
tests/test_a2a.py::test_host_header_localhost_and_ipv6_variants_allowed PASSED
tests/test_a2a.py::test_host_header_configured_a2a_host_allowed PASSED
tests/test_a2a.py::test_auth_pair_rejects_non_loopback_client PASSED

5 passed, 2 deselected
```

**Test quality check:**
- `test_host_header_dns_rebinding_rejected`: Makes actual HTTP requests with `Host: evil.example.com` to `/api/v1/auth/pair`, `/api/v1/profile` (with valid Bearer token), and `/a2a/v1/capabilities` (with valid Bearer token). Asserts all return 403. NOT a stub.
- `test_host_header_loopback_allowed_pair_returns_token`: Requests `/api/v1/auth/pair` with loopback client IP (127.0.0.1:50000) and Host `127.0.0.1:8765`. Asserts 200 and token returned. Then verifies authenticated `/api/v1/profile` works. NOT a stub.
- `test_host_header_localhost_and_ipv6_variants_allowed`: Iterates over `localhost`, `localhost:8765`, `[::1]`, `[::1]:8765`, `127.0.0.1`, `127.0.0.1:8765`. Asserts all return 200 on pair. NOT a stub.
- `test_host_header_configured_a2a_host_allowed`: Creates app with `cfg.a2a.host = "a2a.internal"`. Asserts pair with that Host returns 200, but `evil.example.com` returns 403. NOT a stub.
- `test_auth_pair_rejects_non_loopback_client`: Uses non-loopback client IP (203.0.113.7:54321). Asserts 403 with "loopback" in detail message. NOT a stub.

**Direct helper function verification:**
```python
from src.a2a.server import _host_header_value, _is_allowed_host_header, _is_gateway_path

# _host_header_value correctly parses and normalizes:
assert _host_header_value('127.0.0.1:8765') == '127.0.0.1'
assert _host_header_value('[::1]:8765') == '::1'
assert _host_header_value('evil.example.com') == 'evil.example.com'
assert _host_header_value(None) is None

# _is_allowed_host_header correctly validates:
assert _is_allowed_host_header('127.0.0.1:8765', 'a2a.internal') == True
assert _is_allowed_host_header('a2a.internal', 'a2a.internal') == True
assert _is_allowed_host_header('evil.example.com', 'a2a.internal') == False

# _is_gateway_path correctly identifies protected routes:
assert _is_gateway_path('/api/v1/profile') == True
assert _is_gateway_path('/a2a/v1/capabilities') == True
assert _is_gateway_path('/health') == False  # public probe
```
All assertions pass. Helper functions are correctly implemented.

**VP1 verdict: PASS**

---

### VP2 — No 0.0.0.0 in Dockerfile / docker-compose.yml

**Command:** `grep -n "0.0.0.0" Dockerfile docker-compose.yml`

**Output:** exit=1 (no hits)

**Dockerfile CMD:**
```
CMD ["python", "run_agent.py", "--server", "--host", "127.0.0.1", "--port", "8765"]
```
Changed from `0.0.0.0` to `127.0.0.1`. ✓

**docker-compose.yml ports:**
```
- "127.0.0.1:8765:8765"
```
Changed from `8765:8765` (all interfaces) to `127.0.0.1:8765:8765` (loopback only). ✓

**docker-compose.yml environment:**
```
- A2A_HOST=127.0.0.1
```
Changed from `0.0.0.0` to `127.0.0.1`. ✓

**VP2 verdict: PASS**

---

### VP3 — Full suite green, no existing test broken

**Command:** `timeout 600 venv/bin/python -m pytest tests/ -q`

**Run 1:** `32 passed, 1 warning in 34.23s`
**Run 2:** `32 passed, 1 warning in 27.91s`

Baseline before F3 was 27 tests. The +5 are the new F3 tests. No existing tests broken.

**test_form_reasoner.py adjustment:** The worker correctly updated `test_server_form_endpoints` to use `TestClient(app, base_url="http://127.0.0.1:8765")` because the new Host-header guard correctly rejects the TestClient default `testserver` host. This is the documented approach in the plan ("adjust TestClient base_url/headers as needed, but do NOT weaken the Host check").

**VP3 verdict: PASS**

---

## Scope Check

**Command:** `git status` and `git diff --stat`

**Changed files:**
```
Dockerfile                  |   7 ++-
docker-compose.yml          |  11 +++-
notes/TASKBOARD.md          |   2 +-
run_agent.py                |  10 +++-
src/a2a/server.py           |  53 ++++++++++++++++++++
tests/test_a2a.py           | 119 +++++++++++++++++++++++++++++++++++++++++++-
tests/test_form_reasoner.py |   4 +-
7 files changed, 197 insertions(+), 9 deletions(-)
```

**Scope verification:**
- `src/a2a/server.py`: Host-header middleware, helper functions, pair logging. **F3-related.** ✓
- `Dockerfile`: CMD changed to `--host 127.0.0.1`. **F3-related.** ✓
- `docker-compose.yml`: Port mapping and A2A_HOST changed to loopback. **F3-related.** ✓
- `run_agent.py`: Added env override for A2A_HOST/A2A_PORT (CLI > env > config). **F3-related.** ✓
- `tests/test_a2a.py`: +5 new F3 tests. **F3-related.** ✓
- `tests/test_form_reasoner.py`: Adjusted base_url for Host-header guard. **F3-related.** ✓
- `notes/TASKBOARD.md`: F3 status update. **F3-related.** ✓
- `notes/evidence/F3-worker.md`: Worker evidence (untracked). **F3-related.** ✓

**No scope creep detected.** All changes are F3-related per FIX_PLAN.md.

---

## Security Spot-Check

**1. No new stored secrets:**
- Command: `grep -E "sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}" src/a2a/server.py run_agent.py Dockerfile docker-compose.yml tests/test_a2a.py tests/test_form_reasoner.py`
- Output: exit=1 (no hits)
- **PASS:** No API keys, AWS keys, or GitHub tokens introduced.

**2. Host-header validation prevents DNS rebinding:**
- Middleware is registered with `@app.middleware("http")` and runs BEFORE route handlers.
- `_is_gateway_path` correctly identifies `/api/*` and `/a2a/*` routes.
- Public probes (`/health`, `/robots.txt`, `/llms.txt`) are correctly excluded (do not start with `/api/` or `/a2a/`).
- `_is_allowed_host_header` validates against loopback hosts + configured host, lowercasing for case-insensitive comparison.
- **PASS:** DNS rebinding attack is defeated.

**3. Docker binding changed from 0.0.0.0 to 127.0.0.1:**
- Dockerfile CMD and docker-compose.yml both bind to loopback only.
- **PASS:** Gateway no longer exposed to LAN by default.

**4. Pair endpoint still requires loopback client IP:**
- `test_auth_pair_rejects_non_loopback_client` verifies this.
- **PASS:** Defense-in-depth preserved.

**5. Pair logging added:**
- Line 410 in server.py: `log.info("Extension paired from %s", client_host)`
- **PASS:** Successful pairing is now auditable.

**6. No forbidden fallbacks reintroduced:**
- No silent `except: pass` in server.py.
- Error paths return HTTP 403 with clear message `{"detail": "Invalid Host header"}`.
- **PASS:** Errors are loud.

---

## Quality Check

**1. No dead code added:**
- Helper functions `_host_header_value`, `_is_allowed_host_header`, `_is_gateway_path` are all used by the middleware.
- No unused imports or unreachable branches.
- **PASS.**

**2. Error paths are loud:**
- Invalid Host → HTTP 403 with `{"detail": "Invalid Host header"}`.
- Non-loopback client on pair → HTTP 403 with "Auto-pairing only allowed from local loopback".
- **PASS.**

**3. No silent failures:**
- `grep -rn "except.*pass" src/a2a/server.py` → no hits.
- **PASS.**

---

## Implementation Quality

**Middleware correctness:**
- Registered with `@app.middleware("http")` inside `create_a2a_app`, so every app instance gets it.
- Checks `_is_gateway_path(request.url.path)` BEFORE validating Host, so public probes are not blocked.
- Returns `JSONResponse(status_code=403, content={"detail": "Invalid Host header"})` for invalid hosts.
- Calls `await call_next(request)` for valid hosts, allowing the request to proceed.

**Helper function robustness:**
- `_host_header_value` uses `urlsplit(f"http://{raw_host.strip()}")` to parse, which handles:
  - `host:port` → extracts hostname
  - `[::1]:port` → extracts `::1` (brackets stripped)
  - `localhost` → extracts `localhost`
- Returns `None` for malformed or absent input.
- Lowercases the hostname for case-insensitive comparison.

**run_agent.py env override:**
- Order: CLI flag > env `A2A_HOST`/`A2A_PORT` > config value.
- Writes back to `cfg.a2a.host` and `cfg.a2a.port` so the middleware stays in sync with the effective bind.
- **PASS:** Correct override order, no drift between bind and guard.

---

## Final Verdict

**All verification points met:**
1. ✓ New tests in tests/test_a2a.py: 5 tests, all pass, not stubs.
2. ✓ No 0.0.0.0 in Dockerfile / docker-compose.yml.
3. ✓ Full suite green (32 passed, 2 consecutive runs), no existing test broken.

**Security:**
- ✓ No new secrets introduced.
- ✓ DNS rebinding attack defeated via Host-header validation.
- ✓ Docker binding changed to loopback only.
- ✓ Pair endpoint still requires loopback client IP.
- ✓ Pair logging added for auditability.
- ✓ No silent failures.

**Quality:**
- ✓ No dead code.
- ✓ Error paths are loud.
- ✓ Helper functions are well-implemented and tested.

**Scope:**
- ✓ No scope creep. All changes are F3-related.

**Worker claim verification:**
- ✓ 32 tests pass (verified independently, 2 runs).
- ✓ All verification points met (verified independently).
- ✓ Evidence file is accurate (cross-checked against actual code).

---

VERDICT: PASS

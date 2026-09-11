# F2 — Extension message-channel security (evidence, worker)

Task: FIX_PLAN.md F2. Files touched: `extension/popup.js`, `extension/content.js`.

## Root cause confirmed (verification FIRST)

Before any change, the review findings were reproduced:

```
=== V1: JOBAGENT_AUTOFILL_BROADCAST in extension/ ===
extension/content.js:622:    if (event.data && event.data.type === "JOBAGENT_AUTOFILL_BROADCAST") {
extension/popup.js:357:              window.postMessage({ type: "JOBAGENT_AUTOFILL_BROADCAST", data }, "*");
exit=0          <- present (FAIL per plan)

=== V2: postMessage in extension/ ===
extension/popup.js:357:              window.postMessage({ type: "JOBAGENT_AUTOFILL_BROADCAST", data }, "*");
exit=0          <- present (FAIL per plan)

=== V3: apiToken in content.js ===
extension/content.js:494:    const apiToken = request.apiToken;
exit=0          <- present (FAIL per plan)
```

## Changes made

**`extension/popup.js`**
- Deleted the entire `chrome.scripting.executeScript(... window.postMessage({type:"JOBAGENT_AUTOFILL_BROADCAST", data}, "*") ...)` broadcast block. `chrome.tabs.sendMessage(activeTab.id, payload, ...)` (kept) already reaches content scripts in ALL frames of the tab — runtime messaging is invisible to page scripts, so the broadcast was redundant AND exposed `apiToken` + full candidate profile + base64 documents to arbitrary third-party iframes.
- Removed `apiToken` from the autofill payload. Content.js never used it; the popup-side runtime bridge (`request_gateway_reason`) adds the `Authorization` header itself via `getAuthHeaders()`. Payload now contains only `action`, `profile`, `documents`, `gatewayUrl`.

**`extension/content.js`**
- Deleted the `const apiToken = request.apiToken;` line in `performAutofill` (unused after the above).
- Deleted the entire `window.addEventListener("message", ...)` block accepting `JOBAGENT_AUTOFILL_BROADCAST` from ANY origin/page script. The `chrome.runtime.onMessage` listener (ping / extract_page_content / autofill_form) is the sole entry point; it can only be reached by the extension's own runtime messaging (sender origin is the extension itself).

## Verification points (FIX_PLAN Part F2) — real outputs

**VP1 — no `JOBAGENT_AUTOFILL_BROADCAST` in extension/:**
```
$ grep -rn "JOBAGENT_AUTOFILL_BROADCAST" extension/
# exit=1 (no hits)  PASS
```

**VP2 — no `postMessage` in extension/:**
```
$ grep -rn "postMessage" extension/
# exit=1 (no hits)  PASS
```

**VP3 — no `apiToken` in content.js; popup.js payload object contains none:**
```
$ grep -n "apiToken" extension/content.js
# exit=1 (no hits)  PASS

$ awk '/const payload = \{/,/\};/' extension/popup.js | grep -n "apiToken"
# exit=1 (no hits)  PASS
```
popup.js still uses `apiToken` only where appropriate: storage/getAuthHeaders/pairing/bridge/dashboard — all popup-side, never sent to the page.

**VP4 — runtime-message path intact:**
```
$ grep -n "chrome.runtime.onMessage.addListener" extension/content.js extension/popup.js
extension/content.js:584   <- handles ping / extract_page_content / autofill_form
extension/popup.js:386     <- request_gateway_reason bridge (Authorization added here)

$ grep -n 'action === "autofill_form"' extension/content.js
613:    if (request.action === "autofill_form") {

$ grep -n "chrome.tabs.sendMessage(activeTab.id, payload" extension/popup.js
356:      chrome.tabs.sendMessage(activeTab.id, payload, (res) => {

$ grep -c "ensureContentScriptInjected" extension/popup.js
3                                <- definition + called for archive and for autofill
```
PASS — all-frames delivery is preserved via `chrome.tabs.sendMessage` + `ensureContentScriptInjected` (`allFrames: true` dynamic injection for tabs opened before extension reload).

**Syntax safety nets (files are JS; repo suite is Python only):**
```
$ node --check extension/popup.js && node --check extension/content.js
SYNTAX OK
$ python -c "import json; json.load(open('extension/manifest.json')); print('manifest OK')"
manifest OK
```

**VP5 — full test suite green:**
```
$ timeout 600 venv/bin/python -m pytest tests/ -q
27 passed, 1 warning in 21.93s
```
(Baseline before change: `27 passed, 1 warning in 26.45s` — no regression; the 1 warning is a pre-existing anyio DeprecationWarning from starlette TestClient.)

## Scope / deviations
- Only FIX_PLAN.md F2 files were touched: `extension/popup.js`, `extension/content.js`. No tests import the extension, so no test changes were needed. No secrets, no commits, no DB/report paths touched.
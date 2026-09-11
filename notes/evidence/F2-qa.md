# F2 QA — Extension message-channel security (independent verification)

## Verification points (each run fresh by QA)

### VP1 — `JOBAGENT_AUTOFILL_BROADCAST` absent from extension/
```
$ grep -rn "JOBAGENT_AUTOFILL_BROADCAST" extension/
exit=1   ← NO hits
```
**PASS**

### VP2 — `postMessage` absent from extension/
```
$ grep -rn "postMessage" extension/
exit=1   ← NO hits
```
**PASS**

### VP3 — `apiToken` absent from content.js and popup.js payload object
```
$ grep -n "apiToken" extension/content.js
exit=1   ← NO hits

$ awk '/const payload = \{/,/\};/' extension/popup.js | grep -n "apiToken"
exit=1   ← NO hits
```
Remaining `apiToken` references in popup.js are all popup-side (storage, getAuthHeaders,
pairing, bridge status) — never sent to content scripts or exposed to page scripts.
**PASS**

### VP4 — Runtime-message path intact
```
$ grep -n "chrome.runtime.onMessage" extension/content.js
584:  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
620:  // All communication uses chrome.runtime.onMessage

$ grep -n 'action === "autofill_form"' extension/content.js
613:    if (request.action === "autofill_form") {

$ grep -n "chrome.tabs.sendMessage" extension/popup.js
200:        chrome.tabs.sendMessage(tabId, { action: "ping" }, ...
249:      chrome.tabs.sendMessage(activeTab.id, { action: "extract_page_content" }, ...
356:      chrome.tabs.sendMessage(activeTab.id, payload, ...

$ grep -c "ensureContentScriptInjected" extension/popup.js
3

$ grep -n "chrome.runtime.onMessage" extension/popup.js
384:  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
```
All runtime-message paths (ping, extract_page_content, autofill_form, bridge) intact.
`ensureContentScriptInjected` (definition + 2 call sites) preserved.
**PASS**

### VP5 — Full test suite green
```
$ timeout 600 venv/bin/python -m pytest tests/ -q
27 passed, 1 warning in 21.61s
```
(1 warning = pre-existing anyio DeprecationWarning from starlette TestClient.)
**PASS**

## Scope check
```
$ git diff --stat
 extension/content.js | 10 +++-------
 extension/popup.js   | 19 ++++---------------
 notes/TASKBOARD.md   |  2 +-
 3 files changed, 8 insertions(+), 23 deletions(-)
```
Only F2 files touched. No unrelated changes.

## Security spot-check
- `grep -n 'addEventListener.*message' extension/content.js extension/popup.js` → NO hits.
- `grep -n 'window\.postMessage\|\.postMessage(' extension/content.js extension/popup.js` → NO hits.
- No new stored secrets, no forbidden fallbacks reintroduced.
- Empty catch blocks at popup.js lines 75, 149 are **pre-existing** (confirmed via git stash to baseline) — NOT introduced by F2.

## Quality
- JS syntax valid: `node --check extension/popup.js && node --check extension/content.js` → OK.
- manifest.json valid JSON.
- No dead code added. Comments explain rationale for removal.

VERDICT: PASS

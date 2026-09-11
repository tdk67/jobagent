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

# JobAgent CURRENT_STATUS (ground truth for detached agents)

- Repo: /root/jobagent, branch `main`, remote `git@github.com:tdk67/jobagent.git` (SSH key ~/.ssh/github works).
- HEAD: single sanitized commit `04e93ae` (history squashed 2026-09-12 to purge a real-PII
  test fixture; see TASKBOARD F1). Prior review found the leak; remote history verified clean
  via fresh clone.
- Project: hackathon entry "Agents for Humans" (AWS Strands SDK mandatory), deadline
  **Sept 14, 2026 20:00 EDT**. See HACKATHON_INFO.md and PRD.md.
- Stack: Python 3.12 (`venv/bin/python`), FastAPI A2A gateway (:8765), FastMCP server,
  Strands Agent coordinator, SQLite storage (`data/jobagent.db`, gitignored), Playwright
  PDF rendering, Chrome MV3 extension (`extension/`).
- Test cmd: `timeout 600 venv/bin/python -m pytest tests/ -q` — 27 tests, all green at baseline (~35s).
- Do NOT run the real-data DB. `run_agent.py --demo` uses an isolated demo DB.
- Remediation plan: notes/FIX_PLAN.md (F2–F7). Full review findings live in the plan's
  problem statements. No code changes outside the plan.

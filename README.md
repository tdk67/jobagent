# 🚀 JobAgent
### Autonomous Background Career CRM & Statutory Compliance Engine
*Built with the **AWS Strands Agents SDK** for personal career automation and [Agents for Humans](https://agentsforhumans.devpost.com)*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Powered by Strands](https://img.shields.io/badge/Agent-Strands%20SDK-orange.svg)](https://github.com/strands-agents/harness-sdk)
[![LLM: Google Gemini](https://img.shields.io/badge/LLM-Google%20Gemini%20Flash-blue.svg)](https://ai.google.dev/)
[![Local First](https://img.shields.io/badge/Privacy-100%25%20Local-green.svg)](#-privacy--zero-cloud-pii)

---

## 💡 What is JobAgent?
Job hunting is an exhausting, fragmented process. Job seekers apply across dozens of platforms (LinkedIn, StepStone, Indeed, Personio, Greenhouse, company career sites), leading to:
- Lost job descriptions once postings close or expire.
- Hundreds of unorganized confirmation, rejection, and interview emails across multiple inboxes.
- Marketing spam, paid recruiter webinars, and sales pitches masquerading as genuine job interviews.
- Tedious statutory reporting obligations—such as the mandatory German **Agentur für Arbeit** proof of active job search (*Nachweis über Eigenbemühungen*, § 138 SGB III).

**JobAgent** runs locally on your computer to automate these workflows:
1. 📸 **Dual-Asset Archiving**: Saves clean Markdown (`jd.md`) for LLM briefings and pixel-perfect visual PDF snapshots (`snapshot.pdf`) before postings are removed.
2. 📬 **Multi-Protocol Email Ingestion**: Reads Desktop Outlook (MAPI via `pywin32` on Windows), Gmail (via MCP or IMAP), or generic IMAP to automatically track application statuses.
3. 🎯 **Dual-Signal Interview Detection**: Reconciles incoming emails against your verified application history, semantically filtering out sales pitches and webinars from genuine hiring interviews.
4. 🏛️ **Statutory Compliance & Reporting**: Automatically compiles official German *Agentur für Arbeit* PDF proof tables and candidate KPI dashboards with custom date filtering and calendar-week slicing.
5. 🧩 **Browser Copilot Extension**: Manifest V3 browser extension for 1-click posting capture and private form auto-fill.
6. 🤖 **Agent-to-Agent (A2A) & MCP Server**: Exposes standard Model Context Protocol (MCP) tools and REST/SSE endpoints so parent assistants (Claude Desktop, Cursor, Hermes, OpenClaw) can query and control JobAgent.

---

## 🏗️ Architecture Overview

```
                                  ┌─────────────────────────────────────────┐
                                  │      Parent Personal Agents             │
                                  │   (Claude, Cursor, Hermes, OpenClaw)    │
                                  └───────────────────┬─────────────────────┘
                                                      │ A2A Protocol / MCP
                                                      ▼
┌──────────────────────┐          ┌─────────────────────────────────────────┐
│ Chrome Copilot Ext.  │◄────────►│         A2A Gateway & MCP Server        │
│ (Form Assist/Archive)│ REST API │         (FastAPI + Model Context)       │
└──────────────────────┘          └───────────────────┬─────────────────────┘
                                                      │
                                                      ▼
                                  ┌─────────────────────────────────────────┐
                                  │       Strands Agent Coordinator         │
                                  │    (strands.Agent + Google Gemini)      │
                                  └─────┬──────────────────┬────────────────┘
                                        │                  │
               ┌────────────────────────┴─────────┐        └────────────────────────┐
               ▼                                  ▼                                 ▼
    ┌─────────────────────┐            ┌─────────────────────┐           ┌─────────────────────┐
    │  EmailIngestTool    │            │   JobArchiveTool    │           │  ReportRenderTool   │
    │  • Gmail (MCP/IMAP) │            │   • Full-text MD    │           │  • Candidate Dash   │
    │  • Outlook Desktop  │            │   • Visual PDF Snap │           │  • Headhunter View  │
    │  • Generic IMAP     │            │   • Q&A Memory Cache│           │  • AfA German Table │
    │  • Dual-Signal Det. │            │   • Salary & Notes  │           │  • Playwright PDF   │
    └──────────┬──────────┘            └──────────┬──────────┘           └──────────┬──────────┘
               │                                  │                                 │
               └──────────────────────────┬───────┴─────────────────────────────────┘
                                          │
                                          ▼
                       ┌─────────────────────────────────────┐
                       │     Local-First Private Storage     │
                       │     (SQLite CRM + JSON Cache)       │
                       │    *Strict Zero Cloud PII Leak*     │
                       └─────────────────────────────────────┘
```

---

## 🧠 Multi-Tier Classification & Lifecycle Engine

JobAgent implements a robust **3-tier hybrid triage architecture** designed for high accuracy, zero cloud quota waste, and resilience against real-world class imbalance:

```
Incoming Email (Outlook MAPI / Gmail / IMAP)
   │
   ▼
[ Tier 1: Deterministic Rules ] ──(Definitive signal: "Einladung zum Vorstellungsgespräch", "Absage")──► 100% Precision (0ms)
   │
   ▼ (Ambiguous or un-patterned text)
[ Tier 2: Offline ML Classifier ] ──(Confidence >= 40%)──► Scikit-Learn TF-IDF + Logistic Regression (0 quota, 81.1% accuracy)
   │
   ▼ (Low confidence / edge cases)
[ Tier 3: LLM Semantic Engine ] ──(Chain-of-thought intent extraction)──► Gemini Flash Semantic Reasoning (Quota-managed)
```

### Why a Multi-Tier Approach?
- **Class Imbalance Resilience**: In a real inbox, interview invitations represent less than 1% of correspondence, while status updates and noise make up over 80%. A purely statistical ML model naturally skews toward dominant classes. High-precision Tier 1 rules provide deterministic guarantees so life-critical events (interview invitations and formal rejections) are never missed.
- **Quota & Cost Optimization**: Tier 1 and Tier 2 resolve over 95% of incoming correspondence locally and offline without spending Gemini API tokens or hitting rate limits.
- **Traceable Reasoning**: Every classification records confidence metrics, detected intent, and human-readable reasoning visible directly in the email audit modal.

### Application Lifecycle & Multi-Application Disambiguation
1. **Chronological Status Tracking**: Accurately tracks candidates throughout the lifecycle (Applied → Interview → Rejected). When an application ends in rejection after an interview, the dashboard displays `✕ Rejected` while preserving a `🎯 Had Interview` badge for complete interview visibility.
2. **Multi-Cycle Splitting (Re-applications)**: Automatically identifies when a candidate re-applies to a company after a prior rejection and branches into a discrete new application cycle with the updated submission date.
3. **Multi-Role Portal Splitting**: For recruitment platforms and agencies (e.g. Jobgether, Michael Page, Devoteam) where a candidate submits multiple applications over time without intermediate rejections, JobAgent clusters emails by extracted job role and submission timestamp gaps (>24h apart), creating distinct canonical applications for each position.
4. **Manual & Phone Rejection Preservation**: Protects human-recorded decisions (e.g. rejections received via phone after an interview) so automated email synchronization never wipes manual status notes.

---

## 🚀 Installation & Setup

### 1. Clone and Install Dependencies
```bash
git clone https://github.com/your-username/jobagent.git
cd jobagent

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies and Playwright browser engine
pip install -r requirements.txt
playwright install chromium

# Download ML model weights (from GitHub Releases)
python scripts/download_models.py
```

### 2. Configure Credentials & Personal Profile
JobAgent strictly adheres to clean-code architecture: **zero secrets in code or repository**.

```bash
cp .env.example .env
cp profile.example.json profile.local.json
cp config.example.json config.local.json
```

1. **`.env`** (Secrets only):
   ```env
   GEMINI_API_KEY="your-google-gemini-api-key"
   # Optional: set a static token for the browser extension or A2A gateway
   JOBAGENT_API_TOKEN="your-secure-random-token"
   ```
2. **`profile.local.json`** (Your personal information, git-ignored):
   Update with your actual name, email, address, target roles, and work history. This profile is used locally to render official statutory reports, tailor AI cover letters, and populate form assistant suggestions.

   > [!TIP]
   > **🚀 Fast 30-Second Setup with Local AI Agents (Claude Coworker, Antigravity, Cursor)**:
   > Instead of manually editing hundreds of lines of nested JSON, open the project in your local AI agent workspace and prompt it:
   > 
   > *"Please generate my `profile.local.json` by reading my existing CV at `./my_resume.pdf` (or docx). Follow the exact JSON structure and field names in `profile.example.json`. Ensure `technical_skills`, `work_experience`, bilingual summaries, and CEFR language proficiencies are accurately mapped. Do not transmit or commit my personal data."*
   > 
   > The local agent parses your PDF resume directly on your machine, formats the JSON adhering to `src/core/profile.py` schema, and writes `profile.local.json`—with **zero PII leakage** outside your local machine.

3. **`config.local.json`** (Application settings, git-ignored):
   Configure which email providers to scan (`outlook_desktop`, `imap`, `gmail_mcp`), report styling, and LLM model designations (`gemini-2.5-flash`).

#### Environment Overrides (env wins over config files)

The following environment variables are read at startup and override the
`config.local.json` / `config.example.json` values (precedence: **env >
config.local.json > config.example.json > defaults**):

| Variable | Overrides | Example |
| :--- | :--- | :--- |
| `IMAP_HOST` | `email_ingestion.generic_imap.host` | `imap.test` |
| `IMAP_PORT` | `email_ingestion.generic_imap.port` (int) | `993` |
| `IMAP_USE_SSL` | `email_ingestion.generic_imap.use_ssl` ("1"/"true"/"yes" → True, else False) | `true` |
| `A2A_HOST` | `a2a.host` | `127.0.0.1` |
| `A2A_PORT` | `a2a.port` (int) | `8765` |
| `JOBAGENT_DB` | `storage.database_path` | `data/jobagent.db` |

`IMAP_USER` / `IMAP_PASSWORD` are read directly by the IMAP adapter (see `.env`).
Invalid integer values (e.g. `A2A_PORT=abc`) are logged as warnings and ignored.

---

## 💼 Real-World Daily Usage

### Step 1: Install the Browser Copilot Extension
The extension integrates JobAgent directly into your browser while you apply for jobs:

1. Open **Chrome**, **Brave**, or **Edge** and navigate to `chrome://extensions`.
2. Toggle on **Developer mode** (top-right corner).
3. Click **Load unpacked** and select the `extension/` folder inside this repository (`jobagent/extension`).
4. Start the JobAgent local gateway server:
   ```bash
   python run_agent.py --server
   ```
   *(The server will print an API token and write it to `.jobagent_token`. The extension reads this automatically.)*

#### Applying for Jobs with the Extension:
- **1-Click Posting Archiving**: Whenever you view an interesting job opening on LinkedIn, StepStone, Personio, Greenhouse, or any company page, open the JobAgent extension popup and click **"Archive Job Posting"**.
  - Automatically captures the job description in clean Markdown (`data/archives/<company>_<role>/jd.md`).
  - Captures a high-resolution visual snapshot (`snapshot.pdf`).
  - Registers the application in your local CRM database (`data/jobagent.db`).
- **Private Form Assistant**: When filling out long application forms, click the extension's **"Smart Autofill"** to retrieve matching answers from your `profile.local.json` and canonical Q&A memory. Sensitive data (passwords, bank accounts) are never filled or cached.

---

### Step 2: Ingest & Triage Real Emails
JobAgent can monitor your job hunt inboxes to keep your application statuses up to date without manual data entry.

To scan your real inboxes right now:
```bash
python run_agent.py --triage
```
What this does:
- Scans connected inboxes (Desktop Outlook on Windows, IMAP, or Gmail).
- Matches incoming correspondence against applications in your local database.
- Detects application confirmations and updates status to `Applied`.
- Detects genuine interview invitations, extracts interview dates and secure meeting links, and updates status to `Interview`.
- Logs rejection emails and marks status as `Rejected`.
- Filters out recruiter spam, webinars, and promotional emails.

#### 🔄 Retesting Email Loader from Scratch (Week-by-Week from Outlook)
If you are setting up JobAgent for the first time, or want to verify and re-ingest your historical job hunt emails week-by-week starting from July 1st into an empty database:

1. **Initialize an Isolated Fresh Database**:
   ```bash
   # Creates data/test_fresh.db with empty schemas (preserves your real data/jobagent.db)
   python run_agent.py --db data/test_fresh.db --reset-db
   ```

2. **Ingest Emails Week-by-Week Starting from 1-Jul**:
   ```bash
   # Automatically slices calendar weeks (KW 27, KW 28, ... KW 37) and ingests each week sequentially
   python run_agent.py --db data/test_fresh.db --triage --weekly --start-date 1-Jul
   ```
   *(JobAgent reads your Outlook Desktop folder e.g. `Bewerbung`, parses confirmations, rejections, and interview invitations, and populates your fresh CRM database.)*

3. **Or Ingest a Specific Week / Date Range**:
   ```bash
   python run_agent.py --db data/test_fresh.db --triage --start-date 2026-07-01 --end-date 2026-07-07
   ```

4. **Verify by Generating the Statutory Report**:
   ```bash
   python run_agent.py --db data/test_fresh.db --report afa_table --weekly --start-date 1-Jul
   ```

---

### Step 3: Statutory Compliance & Weekly Reporting
JobAgent generates official, print-ready reports for the German **Agentur für Arbeit / Jobcenter** (*Eigenbemühungsnachweis*, § 138 Abs. 1 Nr. 2 / § 159 SGB III) as well as executive analytics dashboards.

#### 1. Complete Report from Today Back to 1-Jul
To generate a single comprehensive statutory PDF table covering all applications submitted since July 1st up to today:
```bash
python run_agent.py --report afa_table --start-date 1-Jul
```
- Outputs: `output/afa_table_1Jul_to_today.pdf` and `output/afa_table_report.html`.
- Includes official agency layout, candidate metadata, application dates, company names, contact persons, roles, application channels, and current status.

#### 2. Week-by-Week Reports Starting from 1-Jul
If your employment agency caseworker requires submissions organized strictly by calendar week:
```bash
python run_agent.py --report afa_table --start-date 1-Jul --weekly
```
JobAgent automatically slices the timeline from July 1st into individual calendar weeks (KW 27, KW 28, KW 29... up to the current week), rendering a distinct official PDF for each week:
- `output/afa_table_KW27_20260701_20260705.pdf`
- `output/afa_table_KW28_20260706_20260712.pdf`
- `output/afa_table_KW29_20260713_20260719.pdf`
- ...
- `output/afa_table_KW37_20260907_20260911.pdf`

#### 3. Regular Report for the Current Week
To generate a weekly report for just the current calendar week:
```bash
python run_agent.py --report afa_table --weekly
```

#### 4. Candidate Analytics Dashboard
To generate a modern KPI dashboard with response rates, interview conversion metrics, and pipeline status:
```bash
python run_agent.py --report dashboard --start-date 1-Jul
```
- Outputs: `output/dashboard_report.pdf` and `output/dashboard_report.html`.

#### 5. Generate All Reports
To produce the AfA table, KPI dashboard, and headhunter summary simultaneously:
```bash
python run_agent.py --report all --start-date 1-Jul
```

> **Tip:** You can specify dates in multiple human-friendly formats: `--start-date 1-Jul`, `--start-date 01.07.2026`, or `--start-date 2026-07-01`. You can also specify an `--end-date` (e.g. `--end-date 31-Aug`).

---

---

## 🔬 Database Isolation & Environment Switching

JobAgent strictly isolates demonstration data from your real job applications:

| Environment | Database File | Description |
| :--- | :--- | :--- |
| **Production / Daily Use** | `data/jobagent.db` | Your real job applications, Outlook/IMAP email history, and compliance records. |
| **Demo Harness (`--demo`)** | `data/jobagent_demo.db` | Auto-reset sandbox used exclusively for simulations and hackathon walkthroughs. Zero changes to your real DB. |
| **Custom / Fresh Testing** | `--db <path>` | Point any command to an arbitrary database file (e.g. `--db data/test_fresh.db`). |

To reinitialize or clear a database schema:
```bash
# Safely resets only the specified database
python run_agent.py --db data/test_fresh.db --reset-db
```

---

## 🖥️ User Interfaces: Human UI vs. AI Agent Interfaces

JobAgent is built as a **hybrid system** that serves both human job seekers and autonomous AI agents:

### 1. Interfaces for Human Users
- **Chrome Copilot Extension (`extension/`)**: 
  - Visual popup in Chrome/Edge/Brave.
  - One-click job posting archiver (saves clean Markdown + visual PDF snapshot).
  - Private form auto-fill assistant using local profile memory without leaking PII.
- **Interactive Visual Dashboards (`output/*.html`)**:
  - Open `output/dashboard_report.html` in your browser for responsive KPI charts, funnel analysis, and interview cards.
  - Open `output/afa_table_report.html` to preview German statutory compliance tables before printing.
- **CLI Terminal Interface (`run_agent.py`)**:
  - Quick, scriptable commands for bulk triage, weekly date slicing, and PDF rendering.

### 2. Interfaces for AI Agents (A2A & MCP)
- Exposes standard **Model Context Protocol (MCP)** tools and REST/SSE endpoints.
- Allows external AI assistants to act as your autonomous career executive.

---

## 🤖 Recommended AI Agent on Windows & Setup Guide

### Why We Recommend **Claude Desktop**
For Windows users, **[Claude Desktop](https://claude.ai/download)** (by Anthropic) provides the smoothest, most powerful native desktop experience for AI tool use:
- **Native MCP Support**: Connects directly to local Python MCP servers over `stdio`.
- **Autonomous Reasoning**: Intelligently decides when to triage inboxes, archive job postings, and compile statutory reports based on natural conversation.
- **Deep Artifacts**: Renders HTML dashboards, PDF summaries, and tables directly in chat.

*(Alternative for developers: **Cursor IDE** or **Windsurf** on Windows also natively support JobAgent's MCP tools.)*

### Step-by-Step Setup Guide on Windows:

1. **Install Claude Desktop**:
   Download and install the official app from [claude.ai/download](https://claude.ai/download).

2. **Configure JobAgent MCP Server**:
   Press `Win + R`, enter `%APPDATA%\Claude`, and open `claude_desktop_config.json` in your favorite editor (e.g. Notepad or VS Code).
   Add the `jobagent` entry:

   ```json
   {
     "mcpServers": {
       "jobagent": {
         "command": "C:\\Data\\work\\jobagent\\.venv\\Scripts\\python.exe",
         "args": ["-m", "src.a2a.server", "--mcp"],
         "cwd": "C:\\Data\\work\\jobagent"
       }
     }
   }
   ```
   *(Ensure the paths match your actual `jobagent` folder and virtual environment).*

3. **Restart Claude Desktop**:
   Completely quit Claude Desktop from the system tray and reopen it. You will see the **hammer icon 🔨** indicating that JobAgent tools are connected.

4. **Verify with Test Prompts**:
   Try asking Claude:
   - *"Triage my job applications inbox from last week and check if I have any new interview invitations."*
   - *"What is the current status of my application at Chrono24?"*
   - *"Generate an Agentur für Arbeit compliance table for all applications since July 1st."*
   - *"Archive this job posting: https://example.com/job/senior-developer"*

---

## 🌐 Agent Discovery & Web Standards (`robots.txt` & `llms.txt`)

When running the JobAgent gateway (`python run_agent.py --server --port 8765`), JobAgent serves standardized discovery manifests for web crawlers and autonomous agent systems:

- **`GET /robots.txt`**: Standard crawler control file specifying allowed paths and discovery pointers.
- **`GET /llms.txt` & `GET /.well-known/llms.txt`**: Follows the [llmstxt.org](https://llmstxt.org) standard, providing structured Markdown documentation of JobAgent's capabilities, tool endpoints, and usage guidelines for LLM agents.

---

## 🤖 Agent-to-Agent (A2A) & MCP Server Reference

JobAgent exposes the following MCP tools to connected parent agents:

| MCP Tool | Description | Parameters |
| :--- | :--- | :--- |
| `jobagent_triage_inbox` | Scans inboxes (Outlook, IMAP, Gmail) for job updates. | `limit`, `start_date` (e.g. '1-Jul'), `end_date` |
| `jobagent_archive_posting` | Captures job description Markdown, PDF snapshot, and adds to CRM. | `url`, `company`, `role`, `notes` |
| `jobagent_get_interviews` | Retrieves scheduled interviews with dates and verified video links. | None |
| `jobagent_generate_compliance_report` | Compiles statutory Agentur für Arbeit PDF or KPI dashboards. | `report_type` ('afa_table', 'dashboard', 'all'), `start_date`, `end_date`, `weekly` (bool) |
| `jobagent_query_qa_memory` | Retrieves canonical candidate answers for screening questions. | `question`, `category` |

### A2A REST & SSE Gateway:
```bash
python run_agent.py --server --port 8765
```
- **Discovery**: `GET http://127.0.0.1:8765/a2a/v1/capabilities`
- **Agent Discovery Spec**: `GET http://127.0.0.1:8765/llms.txt`
- **Crawler Directives**: `GET http://127.0.0.1:8765/robots.txt`
- **Task Delegation**: `POST http://127.0.0.1:8765/a2a/v1/tasks`
- **Streaming Events (SSE)**: `GET http://127.0.0.1:8765/a2a/v1/events`

---

## 🧪 Automated Testing

JobAgent includes an extensive test suite covering all core functionalities:
```bash
pytest tests/ -v
```

Test coverage includes:
- Anti-phishing sender verification and strict HTTPS meeting link validation
- Bilingual form reasoner mapping, password safety, and confirmation gating
- Canonical QA memory precision and short-query false positive rejection
- RFC 2822 email ingestion, stable Message-ID extraction, and multi-cycle idempotency
- FastMCP tool registration and A2A REST/SSE token authentication
- Dual-asset archiving (Markdown + visual PDF snapshots) with SSRF protection
- Date range filtering and weekly calendar slicing for statutory Agentur für Arbeit PDF generation

---

## 🔒 Privacy & Zero Cloud PII

- **100% Local Storage**: All relational application data, interview records, full-page visual PDF snapshots, and candidate profiles are stored strictly on your local machine (`data/jobagent.db`, `data/snapshots/`, `data/archives/`).
- **No Cloud Database**: No user data or credentials are ever sent to an external database.
- **LLM Inference Leaves the Machine**: Storage is 100% local, but default LLM inference (Gemini or Bedrock) necessarily sends the profile context needed for form reasoning and email classification to the configured provider. Only the data needed for the task is included; inference never stores your data on the provider side.
- **True Local Execution (Ollama)**: If you have a powerful machine (e.g., Apple Silicon Mac, or a PC with a dedicated GPU), you can configure JobAgent to use **Ollama** instead of Gemini. This guarantees that **no sensitive emails or profile data ever leave your machine**, fulfilling the true zero-cloud privacy promise.

### How to use Ollama with JobAgent:
1. Install [Ollama](https://ollama.com/) on your machine.
2. Pull a recommended model (e.g., `ollama pull llama3.2:1b` or `phi3`).
3. In your `config.local.json`, set:
   ```json
   "agent": {
     "provider": "ollama",
     "model": "llama3.2:1b"
   }
   ```
**Performance Expectation**: Smaller models like `llama3.2:1b` or `phi3:latest` run very fast on standard hardware and are usually sufficient for basic zero-shot classification (e.g., detecting if an email is a rejection). However, for complex semantic extraction, larger models (which require more RAM/VRAM) will be much closer to Gemini-level accuracy. If you notice reduced accuracy with local models, you can easily switch back to `gemini` in your config.

- **Strict PII Protection**: Sensitive form fields (passwords, bank accounts, personal identity numbers) are strictly ignored by the form reasoner and never cached in memory.

---

## 📌 Roadmap & Planned Enhancements

- [ ] **Windows Background Daemon & Auto-Start**: Provide a 1-click script (`scripts/register_autostart_task.ps1`) using native **Windows Task Scheduler** and `pythonw.exe` to run the JobAgent server silently as a background daemon upon user logon, auto-restarting after laptop reboots with zero Docker or manual terminal management required.

---

## 📄 License
Released under the [MIT License](LICENSE).

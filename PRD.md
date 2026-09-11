# Product Requirements Document (PRD)
## JobAgent: Autonomous Background Career Agent

**Status:** Hackathon Submission Ready  
**SDK:** AWS Strands Agents SDK (`strands-agents`)  
**License:** MIT  

---

## 1. Problem Statement
Job seekers apply across dozens of platforms (LinkedIn, StepStone, company career sites). This produces:
1. **Data Fragmentation**: Confirmation emails, rejections, and interview requests scatter across Gmail and Outlook.
2. **Fleeting Job Descriptions**: Postings are unpublished as soon as the listing closes; candidates arrive at interviews without remembering what was written.
3. **Sales & Spam Collisions**: B2B sales reps, software pitches, and coaching webinars send Calendly invites that mimic interview invitations.
4. **Compliance Overhead**: In countries like Germany (Agentur für Arbeit) and the US (Unemployment Commissions), job seekers must manually maintain statutory proof tables (*Eigenbemühungsnachweis*).

---

## 2. Architecture Overview
Powered by the **Strands Agents SDK**, JobAgent implements an autonomous model-driven agent with specialized tools:

```
                      ┌─────────────────────────────────┐
                      │    Strands Agent Coordinator    │
                      │    (strands.Agent + LLM Core)   │
                      └────────────────┬────────────────┘
                                       │
         ┌─────────────────────────────┼─────────────────────────────┐
         ▼                             ▼                             ▼
┌───────────────────┐        ┌───────────────────┐        ┌───────────────────┐
│ EmailIngestTool   │        │ JobArchiveTool    │        │ ReportRenderTool  │
│ • Gmail auto-tag  │        │ • Full-text MD    │        │ • Headhunter PDF  │
│ • Outlook COM     │        │ • Visual PDF snap │        │ • AfA German Form │
│ • Generic IMAP    │        │ • Salary & Q&A    │        │ • Interactive Web │
└───────────────────┘        └───────────────────┘        └───────────────────┘
                                       │
                                       ▼
                      ┌─────────────────────────────────┐
                      │   Local-First Private Storage   │
                      │   (Zero Cloud PII Leakage)      │
                      └─────────────────────────────────┘
```

---

## 3. Core Tools & Capabilities

### Tool 1: `EmailIngestTool`
- **Multi-Protocol Adapters**:
  - **Gmail**: Searches candidate emails, classifies them, and applies a structured label tree (`JobSearch/Applications`, `JobSearch/Interviews`, `JobSearch/Rejections`).
  - **Outlook Desktop (COM)**: Direct headless MAPI inspection without OAuth or cloud credentials.
  - **Generic IMAP**: Connects to ProtonMail (via Bridge), Fastmail, iCloud, or custom domains.
- **Dual-Signal Interview Classification**:
  - Reconciles meeting requests against verified past application records.
  - Employs zero-shot semantic LLM analysis to discard sales calls, webinars, and coaching pitches.

### Tool 2: `JobArchiveTool` & Browser Copilot
- **Dual-Asset Preservation**:
  - Extracts clean Markdown (`jd.md`) for fast full-text search and LLM context injection.
  - Captures full-page high-resolution visual PDF snapshots (`snapshot.pdf`) preserving the exact visual layout before listings close.
- **Candidate Q&A Memory**: Records salary expectations and custom screening question answers.

### Tool 3: `ReportRenderTool`
- Generates print-ready PDFs and mobile-responsive dashboards.
- Includes pre-built templates for:
  1. **Candidate Personal Dashboard**: KPI cards, weekly timeline activity, linked email threads.
  2. **Headhunter / Agency View**: Concise applied company list.
  3. **Official German Agentur für Arbeit View**: Statutory *Nachweis über Eigenbemühungen*.

---

## 4. Privacy & Zero-Cloud Guarantee
- All personal profile data (`profile.local.json`), email credentials, and application databases are saved locally.
- Nothing is sent to third-party tracking services or sold to recruiters.

# JobAgent — 3-Minute Video Pitch Plan
> For the **Agents for Humans** hackathon (AWS Strands Agents SDK). Deadline: Sept 14, 2026 20:00 EDT.

## 🎯 Core Message (one sentence)
**JobAgent is a local-first, autonomous career CRM that turns the chaos of job hunting — expiring postings, scattered emails, hidden interview invites — into a single intelligent cockpit, with zero PII leaving your machine.**

## 🎬 Scene-by-Scene (180 seconds)

### 0–15s — Hook (Problem, visceral)
- **Visual**: Split screen: browser tabs flooding (StepStone, LinkedIn, Personio), inbox with 200 unread emails, a calendar with one interview circled.
- **Voiceover**: "Job hunting is chaos. Postings vanish. Interviews hide in your spam. And Germany demands proof of every application you made — or your benefits get cut."
- **On-screen text**: "3 platforms · 200 emails · 1 interview somewhere in there"

### 15–40s — Enter JobAgent (Solution reveal)
- **Visual**: Clean logo animation. The Agent appears: pipeline graphic (Email → Classifier → CRM → Reports).
- **Voiceover**: "Meet JobAgent — built on the **AWS Strands Agents SDK**. An autonomous background agent on your own machine."
- **Text**: "Local-first · Zero cloud PII · AWS Strands Agents SDK"

### 40–75s — Demo 1: Posting Capture (Multi-Asset Archiving)
- **Visual**: Browser extension popup over a job posting on Chrono24/Personio. One click.
- **Voiceover**: "Found a job? One click. JobAgent instantly archives a clean Markdown brief *and* a pixel-perfect PDF snapshot — because that posting will be gone tomorrow."
- **Text**: "1-click capture → Markdown + PDF snapshot"

### 75–115s — Demo 2: Email Triage & Interview Detection (the wow moment)
- **Visual**: Inbox swims in. Three emails appear: a German interview invite, a rejection, and a sales webinar.
- **Voiceover**: "Then the magic. Every email is triaged through **three tiers**: deterministic rules, an offline ML classifier, and Gemini semantic reasoning. Genuine interview invites — even in German — are detected and put on your radar as high-priority alerts."
- **Text**: "3-tier triage: Rules → ML → Gemini"
- **Visual beat**: The "Einladung zum Vorstellungsgespräch" email glows → card flips to "Interview Detected 🎯".

### 115–150s — Demo 3: Statutory Compliance (Agentur für Arbeit)
- **Visual**: Dashboard morphs into the official German AfA proof table (KW weeks, dates, companies).
- **Voiceover**: "And when Agentur für Arbeit asks for proof of your job search — the weekly **Eigenbemühungsnachweis** — JobAgent compiles the official table automatically. A PDF report ready to submit."
- **Text**: "Agentur für Arbeit §138 SGB III — automatic proof table"

### 150–175s — Demo 4 (live if stable): Telegram + A2A
- **Visual**: Telegram chat on phone. `/jobagent status` → stats. `/jobagent report afa` → PDF.
- **Voiceover**: "It's agent-to-agent: ask your Telegram assistant 'what's my status?' and JobAgent answers through the standard A2A interface."
- **Text**: "A2A & MCP — parents (Telegram, Claude, Cursor) talk to JobAgent"

### 175–180s — Close (Vision)
- **Visual**: Logo + tagline.
- **Voiceover**: "JobAgent: your career, your data, your proof — fully automated."
- **Text**: "Agent for Humans · Local-first · JobAgent"

## 🎤 Recording Tips
- **Voice**: energetic, no dead air; rehearse each segment to ~30s.
- **Pacing**: never let any single screen sit >8s without motion/annotation.
- **Zoom/glow effects** on the interview email — it's the emotional core.
- If the live demo is risky, **pre-record** the A2A/Telegram clip and splice in.

## 📦 Assets Needed
| Asset | Source |
|---|---|
| JobAgent logo/favicon | extension icons + docs |
| Screencast of extension capture | Playwright script + OBS |
| Screencast of dashboard/AfA report | Playwright script |
| Telegram /jobagent clip | Playwright script (or phone recording) |
| Synthetic persona + demo DB | `scripts/seed_demo_data.py` |
| Podcast audio (optional) | Frame Talk (`frametalk_synced_*.mp4`) |

## 🗺 Delivery Checklist
- [x] Playwright showcase script renders all screens (HTML/PDFs) on *judge-proof* synthetic data
- [x] Demo DB has a varied, realistic career arc (applied → interview → rejected → applied, re-application, phone rejection preserved)
- [ ] Telegram /jobagent commands verified live
- [x] A2A gateway verified: capabilities, tasks, SSE events
- [x] Frame Talk podcast generated from the screencast
- [ ] Final MP4 ≤ 180s, ≤ 500MB, submitted with README/devpost link

## 📤 Demo-DB switch for the video (important)
The showcase scripts and Frame Talk pipeline ran against `data/jobagent_demo.db` (10 applications, 2 interviews, synthetic „Jane Doe“).

**Before recording the final video, point the LIVE A2A gateway at the demo DB** so `/dashboard` and `/jobagent` in Telegram show the same rich synthetic career arc:
```bash
# in /root/jobagent
JOBAGENT_DB=data/jobagent_demo.db pm2 restart jobagent-a2a --update-env
# verify
curl -s http://127.0.0.1:8765/dashboard | grep -c 'Chrono24'  # expect >0
# and on Telegram: /jobagent report → dashboard PDF with 10 apps
```
After the video, switch back:
```bash
pm2 restart jobagent-a2a --update-env
```
Your own local DB (uploaded from your PC) replaces `data/jobagent.db` — see notes/TELEGRAM_A2A_SETUP.md.
# JobAgent — Telegram + A2A Remote Interface Setup

> Goal: drive JobAgent from Telegram on your phone and expose the full A2A gateway to parent agents, using synthetic/demo data here (since this VPS cannot reach your Outlook inbox).

## 🏗 Architecture (what got wired up)

```
Telegram (Pisti bot, pm2) ── /jobagent … ──► POST :8765/a2a/v1/tasks ──► JobAgent A2A Gateway
                                                                              │
Parent agents (Hermes/pi, MCP clients) ──► :8765/a2a/v1/* ◄───────────────────┘
                                                      │
                                                      ▼
                                       Local SQLite data/jobagent.db
                                       (or data/jobagent_demo.db)
```

- **A2A Gateway** — FastAPI on `127.0.0.1:8765` (pm2 app `jobagent-a2a`), token in `data/../.jobagent_token`.
- **Telegram bot** — `/root/telegram-bot/index.js` (pm2 app `telegram-bot`), new `/jobagent` commands.
- **Demo DB** — `data/jobagent_demo.db` (seeded synthetic persona "Jane Doe / example.com"), used for the pitch video.
- **Real DB** — `data/jobagent.db` — currently small synthetic fixture. Replace with your local copy (below).

## 📋 Telegram commands (on the Pisti bot)

| Command | What it does |
|---|---|
| `/jobagent` | Career CRM status: applications, interviews, rejections, response rate |
| `/jobagent report` | Generate dashboard compliance report (PDF + HTML) |
| `/jobagent report afa` | Generate official German Agentur für Arbeit proof table |
| `/jobagent report agency` | Generate headhunter/agency summary |
| `/jobagent triage [N]` | Run inbox triage on last N emails (uses configured adapters — see below) |
| `/jobagent qa <question>` | Query verified screening Q&A memory |

## 🔐 Token & auth
- Token lives in `/root/jobagent/.jobagent_token` (auto-generated on first run; env `JOBAGENT_API_TOKEN` overrides).
- The bot reads it from that file. All gateway routes require `Authorization: Bearer <token>` (or `X-JobAgent-Token`).
- Host-header guard: only `127.0.0.1`/`localhost`/configured host allowed → DNS-rebinding safe.
- Gateway is loopback-bound; it's **not** exposed to the internet. For remote Telegram access, the bot (already on this host) proxies to it — no inbound exposure needed.

## 📤 Uploading your real DB from your local PC

**Why:** This VPS cannot reach your Outlook desktop (MAPI) or your personal Gmail inbox. So to see *your* real applications, upload your local SQLite DB.

### Step 1 — Export from your PC
On your PC, next to the running JobAgent (or after stopping it):
```bash
# The DB file is data/jobagent.db (SQLite). Copy it out:
cp data/jobagent.db jobagent_local_backup.db
# Optional: also export profile + config
cp profile.json profile_local.json
cp config.local.json config_local.json
```

### Step 2 — Transfer securely (pick one)
```bash
# A: scp (recommended)
scp jobagent_local_backup.db root@<VPS-IP>:/root/jobagent/data/jobagent.db
scp profile_local.json root@<VPS-IP>:/root/jobagent/profile.json

# B: via Telegram to the bot (Pisti handles documents) — upload the .db as a document,
#    it lands in /tmp; then move into place:
#    bash: mv /tmp/jobagent_local_backup.db /root/jobagent/data/jobagent.db
```

### Step 3 — Restart the gateway to pick up the new DB
```bash
pm2 restart jobagent-a2a --update-env
# verify
curl -s http://127.0.0.1:8765/health
# then in Telegram:
#   /jobagent            → should show your real application stats
#   /jobagent report    → your dashboard PDF
```

### Important caveats
- **Format must match**: JobAgent's SQLite schema (migrations auto-apply on startup). If you used a different version, run the migration first on your PC (`venv/bin/python run_agent.py --server` once).
- **Do NOT upload real PII to a public repo.** The git repo must stay synthetic — `.gitignore` already excludes `data/*.db`.
- **Email triage from here** works only via a reachable IMAP/Gmail MCP — configure `config.local.json` with your IMAP host/user/password (or a Gmail app password) if you want live triage from this VPS. Outlook Desktop (MAPI) is Windows-only and will **not** run here.

## 🧪 Verify everything
```bash
# gateway
curl -s -H "Authorization: Bearer $(cat /root/jobagent/.jobagent_token)" \
     http://127.0.0.1:8765/a2a/v1/capabilities | head
# bot
pm2 logs telegram-bot --lines 10 --nostream
# demo db status via gateway (demo mode uses a different db; run_agent.py --demo seeds it)
```

## 🎬 Pitch assets (already built)
| Artifact | Path |
|---|---|
| Screenshot storyboard | `output/showcase/1..5_*.png`, `output/showcase/storyboard.html` |
| Motion screencast (96s) | `output/showcase/video/jobagent_screencast.mp4` |
| Frame Talk podcast (122s, Alex+Sarah) | `output/podcast/frametalk_synced_jobagent.mp4` |
| Podcast audio | `output/podcast/podcast_jobagent.wav` |
| Pipeline cache (scenes/dialogue/chronos) | `output/showcase/pipeline_cache.json` |

Scripts:
- `scripts/seed_demo_data.py` — synthetic demo DB seeder
- `scripts/playwright_showcase.py` — screenshots storyboard
- `scripts/record_screencast.py` — motion screencast MP4
- `scripts/frametalk_podcast.py` — Frame Talk two-host podcast pipeline (cached, resumable)
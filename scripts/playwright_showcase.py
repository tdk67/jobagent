#!/usr/bin/env python3
"""JobAgent — Playwright showcase script for the 3-minute video pitch.

Renders the full JobAgent story on an isolated synthetic demo DB:
  1. Browser extension capture of a job posting (popup + archived Markdown/PDF)
  2. Candidate dashboard (career analytics)
  3. Agentur für Arbeit proof table (statutory compliance)
  4. "Telegram" style A2A interaction panel (live, using the A2A gateway)

Usage:
    venv/bin/python scripts/playwright_showcase.py [--demo-db data/jobagent_demo.db] [--out output/showcase]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, Browser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ─────────────────────────────────────────────────────────────────────
# Static HTML scenes (self-contained, no network, deterministic)
# ─────────────────────────────────────────────────────────────────────
SCENE_EXTENSION = """<!doctype html><html><head><meta charset="utf-8"><title>JobAgent Showcase — Extension Capture</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; font-family:'Segoe UI',system-ui,sans-serif; }
body { background:#eef2f7; display:flex; gap:40px; padding:48px; align-items:flex-start; }
.job { background:#fff; border-radius:16px; padding:32px; width:420px; box-shadow:0 8px 30px rgba(0,0,0,.12); border:1px solid #dfe6ee; }
.job .co { color:#1a73e8; font-weight:600; font-size:13px; letter-spacing:.06em; text-transform:uppercase; }
.job h1 { font-size:22px; margin:8px 0 12px; color:#0d1b2a; }
.job .meta { color:#5a6b7b; font-size:14px; margin-bottom:18px; }
.job .tags span { display:inline-block; background:#e8f0fe; color:#1a73e8; border-radius:20px; padding:4px 12px; font-size:12px; margin:0 6px 6px 0; }
.job .salary { background:#f0f9f3; color:#147a46; font-weight:700; border-radius:10px; padding:10px 14px; font-size:14px; margin-top:10px; }
.popup { background:#fff; border-radius:16px; width:300px; box-shadow:0 18px 50px rgba(0,0,0,.25); border:1px solid #cfd8e3; overflow:hidden; }
.popup .head { background:linear-gradient(135deg,#1a73e8,#0d47a1); color:#fff; padding:14px 16px; display:flex; align-items:center; gap:10px; }
.popup .head .dot { width:10px; height:10px; border-radius:50%; background:#8ef7b0; }
.popup .head b { font-size:15px; }
.popup .body { padding:16px; }
.popup .field { border:1px solid #dbe4ee; border-radius:8px; padding:9px 12px; margin-bottom:10px; font-size:13px; color:#334; }
.popup .field b { color:#1a73e8; }
.popup .btn { background:#1a73e8; color:#fff; border:none; width:100%; padding:11px; border-radius:8px; font-weight:700; font-size:14px; cursor:pointer; }
.popup .ok { background:#3ddc84; color:#0b3d1f; border:none; width:100%; padding:11px; border-radius:8px; font-weight:700; font-size:14px; margin-top:10px; display:none; }
.annot { position:absolute; top:60px; right:70px; background:#ffd54d; color:#5d4037; font-weight:800; font-size:15px; padding:10px 16px; border-radius:10px; box-shadow:0 4px 12px rgba(0,0,0,.2); transform:rotate(3deg); }
.annot::after { content:''; position:absolute; left:-12px; top:50%; border:8px solid transparent; border-right-color:#ffd54d; border-left-width:0; transform:translateY(-50%); }
</style></head><body>
<div class="job" id="jobcard">
  <div class="co">Chrono24 GmbH</div>
  <h1>(Senior) Java Developer (m/f/d)</h1>
  <div class="meta">Karlsruhe / Remote · Full-time · Posted 2 days ago</div>
  <div class="tags"><span>Java</span><span>Spring Boot</span><span>PostgreSQL</span><span>Kafka</span></div>
  <div class="salary">💶 75.000 – 95.000 EUR</div>
</div>
<div class="popup" id="popup">
  <div class="head"><span class="dot"></span><b>JobAgent Copilot</b></div>
  <div class="body">
    <div class="field">🏢 <b>Chrono24 GmbH</b></div>
    <div class="field">💼 <b>(Senior) Java Developer (m/f/d)</b></div>
    <div class="field">📍 Karlsruhe / Remote</div>
    <button class="btn" id="capture">📸 Archive posting</button>
    <button class="ok" id="ok">✅ Saved · Markdown + PDF snapshot</button>
  </div>
</div>
<div class="annot">One click!</div>
<script>
const btn=document.getElementById('capture'), ok=document.getElementById('ok');
btn.addEventListener('click',()=>{btn.style.display='none'; ok.style.display='block';
  document.querySelector('.annot').textContent='Archived instantly!';});
</script>
</body></html>"""

SCENE_SLIDERECAP = """<!doctype html><html><head><meta charset="utf-8"><title>JobAgent Showcase — Triage</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; font-family:'Segoe UI',system-ui,sans-serif; }
body { background:#eef2f7; padding:40px 60px; }
h1 { color:#0d1b2a; font-size:22px; margin-bottom:6px; }
.sub { color:#5a6b7b; margin-bottom:24px; font-size:14px; }
.pipeline { display:flex; gap:14px; margin-bottom:28px; }
.pipe { flex:1; background:#fff; border:2px solid #dfe6ee; border-radius:12px; padding:14px; text-align:center; font-weight:700; font-size:13px; color:#334; position:relative; }
.pipe .n { font-size:11px; color:#1a73e8; display:block; margin-bottom:6px; }
.pipe.active { border-color:#1a73e8; box-shadow:0 0 0 4px rgba(26,115,232,.12); }
.pipe.done { border-color:#3ddc84; background:#f0fbf4; }
.inbox { display:flex; flex-direction:column; gap:12px; }
.mail { background:#fff; border-radius:12px; padding:14px 16px; border:1px solid #dfe6ee; display:flex; align-items:center; gap:14px; box-shadow:0 2px 8px rgba(0,0,0,.05); }
.mail .ic { width:38px; height:38px; border-radius:10px; display:flex; align-items:center; justify-content:center; font-size:18px; }
.mail .tx { flex:1; }
.mail .subj { font-weight:600; color:#0d1b2a; font-size:14px; }
.mail .from { font-size:12px; color:#6b7a8a; }
.mail .badge { border-radius:20px; padding:5px 12px; font-size:12px; font-weight:700; }
.badge.interview { background:#ffe9e9; color:#c62828; border:1px solid #ffb3b3; }
.badge.reject { background:#ececec; color:#555; }
.badge.noise { background:#e8f0fe; color:#1a73e8; }
.badge.detect { background:#3ddc84; color:#0b3d1f; }
.mail.hl { border:2px solid #ffd54d; box-shadow:0 0 0 6px rgba(255,213,77,.25); }
</style></head><body>
<h1>📬 Inbox Triage — 3-Tier Intelligence</h1>
<div class="sub">Deterministic rules → Offline ML → Gemini semantic reasoning</div>
<div class="pipeline">
  <div class="pipe done"><span class="n">Tier 1</span>✅ Rules<br><small>high-precision patterns</small></div>
  <div class="pipe done"><span class="n">Tier 2</span>🧠 ML<br><small>offline TF-IDF</small></div>
  <div class="pipe active"><span class="n">Tier 3</span>✨ Gemini<br><small>semantic intent</small></div>
</div>
<div class="inbox">
  <div class="mail hl" id="m1">
    <div class="ic" style="background:#ffe9e9">🎯</div>
    <div class="tx"><div class="subj">Einladung zum Vorstellungsgespräch: Senior Java Developer</div><div class="from">recruiting@chrono24.com · 14:30</div></div>
    <div class="badge detect" id="b1">Interview Detected</div>
  </div>
  <div class="mail">
    <div class="ic" style="background:#ececec">❌</div>
    <div class="tx"><div class="subj">Ihre Bewerbung bei Finanz Informatik</div><div class="from">hr@f-i.de · yesterday</div></div>
    <div class="badge reject">Rejection</div>
  </div>
  <div class="mail">
    <div class="ic" style="background:#e8f0fe">📢</div>
    <div class="tx"><div class="subj">Exklusives Webinar für Vertrieb und Finanzkonzepte!</div><div class="from">promo@salescoach.example.com · spam</div></div>
    <div class="badge noise">Noise → discarded</div>
  </div>
</div>
<script>
const badges=['🔍 Analyzing…','✅ Rule match','🧠 ML 0.81 confidence','🎯 Interview Detected'];
let i=0; setInterval(()=>{ i=(i+1)%badges.length; document.getElementById('b1').textContent=badges[i];
  document.getElementById('b1').className='badge '+(i===3?'detect':'interview'); },1200);
</script>
</body></html>"""

SCENE_TELEGRAM = """<!doctype html><html><head><meta charset="utf-8"><title>JobAgent Showcase — A2A / Telegram</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; font-family:'Segoe UI',system-ui,sans-serif; }
body { background:#0b1a2c; display:flex; align-items:center; justify-content:center; min-height:100vh; padding:30px; }
.phone { width:380px; background:#0e2137; border-radius:30px; border:2px solid #1d3a5c; box-shadow:0 20px 60px rgba(0,0,0,.6); overflow:hidden; }
.screen { padding:18px; display:flex; flex-direction:column; gap:12px; min-height:560px; }
.chat { padding:10px 12px; border-radius:12px; font-size:13px; line-height:1.5; max-width:85%; }
.me { background:#1a73e8; color:#fff; align-self:flex-end; border-bottom-right-radius:3px; }
.agent { background:#16283d; color:#dce6f5; align-self:flex-start; border-bottom-left-radius:3px; }
.agent b { color:#5ec3ff; }
.agent .mono { font-family:ui-monospace,Menlo,monospace; color:#8ef7b0; font-size:12px; }
.typing { color:#7d8fa3; font-size:11px; align-self:flex-start; }
.title { text-align:center; color:#69a8d8; font-size:11px; letter-spacing:.1em; text-transform:uppercase; margin-bottom:4px; }
.card { background:#16283d; border-radius:12px; padding:12px; color:#dce6f5; font-size:12px; border:1px solid #24405f; align-self:flex-start; width:100%; }
.card .row { display:flex; justify-content:space-between; padding:3px 0; }
.card .k { color:#7d8fa3; }
.card .v { color:#fff; font-weight:600; }
.card .hl { color:#3ddc84; }
</style></head><body>
<div class="phone"><div class="screen">
  <div class="title">JobAgent · A2A Gateway</div>
  <div class="chat me">/jobagent status</div>
  <div class="typing">JobAgent working…</div>
  <div class="card" id="statcard">
    <div class="row"><span class="k">Applications</span><span class="v">10</span></div>
    <div class="row"><span class="k">Interviews</span><span class="v hl">2</span></div>
    <div class="row"><span class="k">Rejections</span><span class="v">3</span></div>
    <div class="row"><span class="k">Pending</span><span class="v">5</span></div>
    <div class="row"><span class="k">Response rate</span><span class="v hl">50%</span></div>
  </div>
  <div class="chat me">/jobagent report afa</div>
  <div class="typing">Generating Agentur für Arbeit proof table…</div>
  <div class="chat agent">📄 <b>Report generated</b><br><span class="mono">output/afa_table_report.pdf</span><br>17 applications · KW 35–37 · ready to submit</div>
</div></div>
</body></html>"""


def render_dashboard_scene(demo_db: str, out_dir: Path) -> Path:
    """Generate the dashboard + AfA reports from demo DB and stage them."""
    from src.core.config import load_config
    from src.core.profile import load_profile
    from src.core.storage import JobAgentStorage
    from src.services.report_service import ReportService

    cfg = load_config()
    cfg.storage.database_path = demo_db
    db = JobAgentStorage(demo_db)
    prof = load_profile()
    svc = ReportService(storage=db, config=cfg, profile=prof)
    html_map = {}
    for view in ("dashboard", "afa_table"):
        r = svc.generate(view_type=view, export_pdf=False)
        html_map[view] = Path(r["html_path"])
    return html_map["dashboard"], html_map["afa_table"]


def get_live_status() -> dict:
    """Query the running A2A gateway (if up) to power the Telegram scene live."""
    try:
        token = (ROOT / ".jobagent_token").read_text().strip()
        import urllib.request
        req = urllib.request.Request(
            "http://127.0.0.1:8765/a2a/v1/tasks",
            data=json.dumps({"action": "get_status", "payload": {}}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return None


def screenshot(page: Page, path: Path, full: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path), full_page=full)
    print(f"  📸 {path.name} ({path.stat().st_size//1024} KB)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-db", default=str(ROOT / "data/jobagent_demo.db"))
    ap.add_argument("--out", default=str(ROOT / "output" / "showcase"))
    ap.add_argument("--live", action="store_true", help="Query live A2A gateway for Telegram scene")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # Pre-render the real JobAgent dashboard + AfA reports from demo DB
    print("➤ Rendering JobAgent reports from demo DB…")
    dash_html, afa_html = render_dashboard_scene(args.demo_db, out)

    with sync_playwright() as p:
        browser: Browser = p.chromium.launch(headless=True, args=["--force-device-scale-factor=2"])
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)

        # ── Scene 1: Extension capture ───────────────────────────────
        print("➤ Scene 1: Extension capture")
        pg = ctx.new_page()
        pg.set_content(SCENE_EXTENSION)
        pg.evaluate("document.getElementById('capture').click()")
        time.sleep(0.6)
        screenshot(pg, out / "1_capture.png", full=True)
        pg.close()

        # ── Scene 2: 3-tier triage animation ─────────────────────────
        print("➤ Scene 2: Inbox triage")
        pg = ctx.new_page()
        pg.set_content(SCENE_SLIDERECAP)
        time.sleep(1.8)  # catch the interview-detected badge state
        screenshot(pg, out / "2_triage.png", full=True)
        pg.close()

        # ── Scene 3: Real dashboard (demo data) ──────────────────────
        print("➤ Scene 3: Candidate dashboard")
        pg = ctx.new_page()
        pg.goto(dash_html.as_uri())
        time.sleep(1.0)
        screenshot(pg, out / "3_dashboard.png", full=True)
        pg.close()

        # ── Scene 4: AfA proof table ─────────────────────────────────
        print("➤ Scene 4: German AfA proof table")
        pg = ctx.new_page()
        pg.goto(afa_html.as_uri())
        time.sleep(1.0)
        screenshot(pg, out / "4_afa_table.png", full=True)
        pg.close()

        # ── Scene 5: Telegram / A2A panel ────────────────────────────
        print("➤ Scene 5: Telegram / A2A")
        pg = ctx.new_page()
        pg.set_content(SCENE_TELEGRAM)
        if args.live:
            st = get_live_status()
            if st and st.get("status") == "completed":
                s = st["result"].get("statistics", {})
                pg.evaluate(
                    """(S)=>{const rows=[['Applications',S.total_applications||0],['Interviews',S.total_interviews||0],
                    ['Rejections',S.total_rejections||0],['Pending',S.total_pending||0],
                    ['Response rate',(S.response_rate_percent||0)+'%']];
                    const card=document.getElementById('statcard'); card.innerHTML='';
                    rows.forEach(([k,v])=>{const d=document.createElement('div');d.className='row';
                    d.innerHTML=`<span class="k">${k}</span><span class="v">${v}</span>`;card.appendChild(d);});}""",
                    s,
                )
        time.sleep(0.6)
        screenshot(pg, out / "5_telegram_a2a.png", full=True)
        pg.close()

        # ── Also export a compiled "storyboard" HTML for reference ───
        story = out / "storyboard.html"
        imgs = sorted(out.glob("[0-9]_*.png"))
        cards = "\n".join(
            f'<div class="card"><img src="{i.name}" alt="{i.stem}"><div class="cap">{i.stem}</div></div>'
            for i in imgs
        )
        story.write_text(
            f"<!doctype html><html><head><meta charset=utf-8><title>JobAgent Storyboard</title>"
            f"<style>body{{background:#0d1b2a;color:#fff;font-family:system-ui;padding:30px}}"
            f".grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:20px}}"
            f".card{{background:#16283d;border-radius:12px;overflow:hidden;border:1px solid #24405f}}"
            f"img{{width:100%;display:block}} .cap{{padding:8px 12px;font-size:13px;color:#8ef7b0}}</style>"
            f"<h1>🎬 JobAgent — 3-min video storyboard</h1><div class=grid>{cards}</div></body></html>"
        )
        print(f"  📄 storyboard.html")

        browser.close()
    print(f"\n✅ Showcase complete → {out}")


if __name__ == "__main__":
    main()
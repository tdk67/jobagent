#!/usr/bin/env python3
"""JobAgent — record a motion screencast .mp4 for the Frame Talk podcast pipeline.

Replays the showcase scenes as a real browser session with movement and waits on a
SINGLE page (keeps Playwright's video recording continuous), yielding an .mp4 in
`output/showcase/video/`. This video can then be fed into Frame Talk
(analyze-video → generate-script → synthesize-audio → compile-video).

Usage:
    venv/bin/python scripts/record_screencast.py [--demo-db data/jobagent_demo.db] [--seconds 90]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.playwright_showcase import (  # noqa: E402
    SCENE_EXTENSION,
    SCENE_SLIDERECAP,
    SCENE_TELEGRAM,
    render_dashboard_scene,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-db", default=str(ROOT / "data/jobagent_demo.db"))
    ap.add_argument("--out", default=str(ROOT / "output" / "showcase" / "video"))
    ap.add_argument("--seconds", type=float, default=80.0)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print("➤ Rendering JobAgent reports…")
    dash_html, afa_html = render_dashboard_scene(args.demo_db, out.parent)

    n_scenes = 5
    per_scene = max(12.0, args.seconds / n_scenes)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(out),
            record_video_size={"width": 1280, "height": 720},
        )
        page = ctx.new_page()
        scenes = [
            ("1_capture", SCENE_EXTENSION),
            ("2_triage", SCENE_SLIDERECAP),
            ("3_dashboard", dash_html),
            ("4_afa_table", afa_html),
            ("5_telegram", SCENE_TELEGRAM),
        ]
        for name, target in scenes:
            print(f"  🎬 {name} ({per_scene:.0f}s)")
            if isinstance(target, Path) or (isinstance(target, str) and target.startswith("file://")):
                page.goto(target.as_uri() if isinstance(target, Path) else target)
            else:
                page.set_content(target)
            time.sleep(per_scene)
        page.close()
        ctx.close()
        browser.close()

    webm = sorted(out.glob("*.webm"))
    if not webm:
        print("❌ No video recorded"); sys.exit(1)
    mp4 = out / "jobagent_screencast.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(webm[-1]), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         "-an", str(mp4)],
        check=True, capture_output=True,
    )
    dur = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    size_mb = mp4.stat().st_size / 1e6
    print(f"✅ Screencast: {mp4} ({float(dur):.1f}s, {size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""JobAgent — Frame Talk podcast pipeline driver.

Uploads the JobAgent screencast + README to the local Frame Talk instance and runs
the full multimodal pipeline:
    upload → analyze-video → generate-script → synthesize-audio → compile-video
producing a two-host technical podcast (Alex & Sarah) synchronized to the screencast.

Usage:
    venv/bin/python scripts/frametalk_podcast.py [--video output/showcase/video/jobagent_screencast.mp4]
                                              [--base http://127.0.0.1:8010]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

USER_ID = "usr_test_jobagent_pitch_2026"  # allowed hosted-key user (see user_context.py)
VIDEO_DURATION_SEC = 96.0


def http_json(url: str, method: str = "GET", body: dict | None = None,
              headers: dict | None = None, timeout: int = 300, socket_timeout: int | None = None) -> dict | None:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-FrameTalk-User-Id", USER_ID)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=socket_timeout or timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print(f"  ⚠ HTTP {e.code}: {e.read().decode()[:300]}")
        return None
    except Exception as e:
        print(f"  ⚠ {e}")
        return None


def upload_assets(base: str, video: Path) -> dict | None:
    """Multipart upload of video + README via urllib (no requests dependency)."""
    boundary = "----JobAgentFT" + hashlib.md5(video.name.encode()).hexdigest()
    body = bytearray()
    readme = (ROOT / "README.md").read_bytes()
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="readme"; filename="README.md"\r\n'
    body += b"Content-Type: text/markdown\r\n\r\n" + readme + b"\r\n"
    body += f"--{boundary}\r\n".encode()
    body += (f'Content-Disposition: form-data; name="video"; filename="{video.name}"\r\n').encode()
    body += b"Content-Type: video/mp4\r\n\r\n" + video.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(f"{base}/api/upload", data=bytes(body), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("X-FrameTalk-User-Id", USER_ID)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print(f"  ⚠ upload HTTP {e.code}: {e.read().decode()[:400]}")
        return None
    except Exception as e:
        print(f"  ⚠ upload: {e}")
        return None


def wait_job(base: str, job_id: str, timeout_s: int = 900) -> dict | None:
    start = time.time()
    while time.time() - start < timeout_s:
        st = http_json(f"{base}/api/jobs/{job_id}", timeout=30)
        s = (st or {}).get("status")
        if s in ("COMPLETED", "DONE", "SUCCEEDED"):
            return st
        if s in ("FAILED", "ERROR"):
            print(f"  ✗ job failed: {json.dumps(st)[:400]}")
            return None
        time.sleep(8)
    print(f"  ✗ job {job_id} timed out")
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default=str(ROOT / "output/showcase/video/jobagent_screencast.mp4"))
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--cache", default=str(ROOT / "output" / "showcase" / "pipeline_cache.json"))
    ap.add_argument("--skip-upload", action="store_true", help="Resume from cached state")
    args = ap.parse_args()
    video = Path(args.video)
    if not video.exists():
        print(f"❌ video not found: {video}")
        sys.exit(1)
    base = args.base.rstrip("/")
    cache_path = Path(args.cache)
    cache: dict = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    video_filename = cache.get("video_filename")
    readme_text = cache.get("readme_text", "")
    video_hash = cache.get("video_hash")

    if not args.skip_upload or not video_filename:
        print("➤ 1/5 Uploading screencast + README…")
        up = upload_assets(base, video)
        if not up:
            sys.exit(1)
        video_filename = up.get("video_filename")
        readme_text = up.get("readme_text", "")
        video_hash = up.get("video_hash")
        cache.update({"video_filename": video_filename, "readme_text": readme_text, "video_hash": video_hash})
        cache_path.write_text(json.dumps(cache))
        print(f"  ✓ video={video_filename} hash={video_hash}")

    if "scenes" not in cache:
        print("➤ 2/5 Analyzing video (Gemini multimodal)…")
        ana = http_json(f"{base}/api/analyze-video", "POST", {
            "video_filename": video_filename,
            "readme_text": readme_text,
            "video_duration_seconds": VIDEO_DURATION_SEC,
            "video_hash": video_hash,
        })
        if not ana or "job_id" not in ana:
            print("❌ analyze-video failed"); sys.exit(1)
        job_id = ana["job_id"]
        res = wait_job(base, job_id)
        if not res:
            sys.exit(1)
        scenes = res.get("result", {}).get("scenes") or res.get("scenes") or []
        cache["scenes"] = scenes
        cache_path.write_text(json.dumps(cache))
        print(f"  ✓ analyzed: {len(scenes)} scenes")
    else:
        scenes = cache["scenes"]
        print(f"  ⏭ cached scenes: {len(scenes)}")

    if "dialogue" not in cache:
        print("➤ 3/5 Generating two-host dialogue (Alex & Sarah)…")
        script = http_json(f"{base}/api/generate-script", "POST", {
            "scenes": scenes,
            "readme_text": readme_text,
        })
        if not script:
            print("❌ generate-script failed"); sys.exit(1)
        dialogue = script.get("dialogue") or []
        cache["dialogue"] = dialogue
        cache_path.write_text(json.dumps(cache))
        print(f"  ✓ dialogue: {script.get('total_turns', len(dialogue))} turns")
    else:
        dialogue = cache["dialogue"]
        print(f"  ⏭ cached dialogue: {len(dialogue)} turns")

    if "synth" not in cache:
        print("➤ 4/5 Synthesizing audio + Chronos align (Gemini TTS)…")
        synth = http_json(f"{base}/api/synthesize-audio", "POST", {
            "session_id": f"jobagent_{int(time.time())}",
            "scenes": scenes,
            "dialogue": dialogue,
            "voice_alex": "Puck",
            "voice_sam": "Kore",
        }, timeout=900)
        if not synth:
            print("❌ synthesize-audio failed (audio may exist; check output/)"); sys.exit(1)
        cache["synth"] = {
            "session_id": synth.get("session_id"),
            "audio_filename": synth.get("audio_filename"),
            "chronos_schedule": synth.get("chronos_schedule", {}),
        }
        cache_path.write_text(json.dumps(cache))
        print(f"  ✓ audio={synth.get('audio_filename')} total={synth.get('total_audio_ms')}ms")
    else:
        print(f"  ⏭ cached synth: {cache['synth'].get('audio_filename')}")

    print("➤ 5/5 Compiling final podcast video…")
    comp = http_json(f"{base}/api/compile-video", "POST", {
        "session_id": cache["synth"]["session_id"],
        "video_filename": video_filename,
        "audio_filename": cache["synth"]["audio_filename"],
        "chronos_schedule": cache["synth"].get("chronos_schedule", {}),
    }, timeout=60, socket_timeout=20)  # fast fail; poll for output below
    # The compile may finish server-side even if our read timed out — poll for the MP4
    out_name = f"frametalk_synced_{cache['synth']['session_id'][:8]}.mp4"
    ft_output = Path(base.split("//")[-1].split(":")[0] if "://" in base else "") or None
    # The frame-talk output dir is on this same host
    potential = [
        Path("/root/frame-talk/output") / out_name,
        Path("/root/frame-talk/output/frametalk_synced_jobagent.mp4"),
    ]
    deadline = time.time() + 300
    compiled = None
    while time.time() < deadline:
        for p in potential:
            if p.exists() and p.stat().st_mtime > time.time() - 400:
                compiled = p
                break
        if compiled:
            break
        time.sleep(5)
    if compiled:
        print(f"\n✅ Podcast compiled: {compiled} ({compiled.stat().st_size/1e6:.1f} MB)")
        print(f"   (api response: {comp})")
    else:
        print(f"\n⚠ Compile response: {comp}")
        print("   Output not detected in /root/frame-talk/output yet — check manually.")


if __name__ == "__main__":
    main()
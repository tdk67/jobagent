#!/usr/bin/env python3
"""JobAgent — push local data to the VPS phone-mirror (ONE-WAY, no merging).

Purpose: Your VPS cannot reach your email accounts, so it only holds a *copy*
of your data so you can query JobAgent from your phone via Telegram / A2A.
This script pushes that copy: laptop → VPS.

What it syncs (from your local jobagent folder):
  - data/jobagent.db            (the CRM — always)
  - profile.json                (candidate profile — first time / if changed)
  - config.local.json           (only if you create one)

How it works:
  1. Safe SQLite export (VACUUM INTO) so the live DB is never corrupted.
  2. rsync over SSH to a staging dir on the VPS.
  3. Triggers the VPS receive hook (validates, atomic-swap, restarts gateway).

Requirements (on your PC):
  - Python 3.8+
  - rsync  (Git Bash / WSL / MSYS2 on Windows  <--- easiest is Git Bash)
  - SSH key installed on the VPS (see SSH_SETUP in notes/TELEGRAM_A2A_SETUP.md)

Usage:
  python sync_to_vps.py [--host 187.124.171.89] [--user root]
                        [--ssh-key C:\\Users\\you\\.ssh\\id_ed25519]
                        [--jobagent-dir C:\\path\\to\\jobagent]
                        [--port 22] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

VPS_INCOMING = "~/jobagent/sync/incoming"       # staging dir (rsync target)
VPS_HOOK = "~/jobagent/scripts/vps_receive_hook.sh"  # post-receive hook
DEFAULT_KEY = "~/.ssh/jobagent_sync_ed25519"          # key created on the VPS for convenience (see notes)


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def run(cmd: list[str], dry: bool = False, timeout: int = 300) -> subprocess.CompletedProcess:
    log("$ " + " ".join(cmd))
    if dry:
        return subprocess.CompletedProcess(cmd, 0)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def sqlite_export(src: Path, dst: Path) -> bool:
    """VACUUM INTO a temp copy — safe even while the app is running."""
    if not src.exists():
        return False
    try:
        con = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=10)
        con.execute(f"VACUUM INTO ?", (str(dst),))
        con.close()
        return dst.stat().st_size > 0
    except Exception as e:
        log(f"⚠ sqlite export failed: {e}")
        return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="187.124.171.89")
    ap.add_argument("--user", default="root")
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--ssh-key", default=DEFAULT_KEY, help="path to private key authorized on the VPS")
    ap.add_argument("--jobagent-dir", default=".", help="local jobagent checkout")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ja = Path(args.jobagent_dir).expanduser()
    if not (ja / "data" / "jobagent.db").exists():
        log(f"❌ no jobagent.db at {ja}/data/jobagent.db — point --jobagent-dir at your local repo")
        sys.exit(1)

    key = Path(args.ssh_key).expanduser()
    if not key.exists():
        log(f"❌ ssh key not found: {key}")
        sys.exit(1)

    dest = f"{args.user}@{args.host}"
    ssh_base = ["ssh", "-i", str(key), "-p", str(args.port), "-o", f"StrictHostKeyChecking=accept-new"]

    # 1. Build a staging folder with a safe (VACUUM'd) DB + optional profile/config
    with tempfile.TemporaryDirectory(prefix="jobagent-sync-") as tmp:
        staging = Path(tmp) / "incoming"
        staging.mkdir()

        if sqlite_export(ja / "data" / "jobagent.db", staging / "jobagent.db"):
            log(f"✓ exported DB ({staging/'jobagent.db'})")
        else:
            log("❌ could not export DB"); sys.exit(1)

        for extra in ("profile.json", "config.local.json"):
            p = ja / extra
            if p.exists():
                shutil.copy2(p, staging / extra)
                log(f"✓ including {extra}")

        # 2. rsync to VPS staging (only changed bytes)
        rsync_cmd = [
            "rsync", "-avz", "--delete", "-e", f"ssh -i {key} -p {args.port} -o StrictHostKeyChecking=accept-new",
            f"{staging}/", f"{dest}:{VPS_INCOMING}/",
        ]
        r = run(rsync_cmd, args.dry_run)
        if r.returncode != 0 and not args.dry_run:
            log("❌ rsync failed: " + (r.stderr or r.stdout)[-500:])
            sys.exit(1)

        # 3. Trigger the VPS receive hook (validates, swaps, restarts gateway)
        hook = ssh_base + [dest, f"bash {VPS_HOOK} pc-inbox"]
        r2 = run(hook, args.dry_run)
        if r2.returncode != 0 and not args.dry_run:
            log("❌ hook failed: " + (r2.stderr or r2.stdout)[-500:])
            sys.exit(1)

    if args.dry_run:
        log("(dry-run — nothing pushed)")
    else:
        log("✅ sync complete — phone/TG now sees the fresh DB")


if __name__ == "__main__":
    main()
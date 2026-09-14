#!/usr/bin/env python3
"""JobAgent — push local data to the VPS phone-mirror (ONE-WAY, no merging).

Purpose: Your VPS cannot reach your email accounts, so it only holds a *copy*
of your data so you can query JobAgent from your phone via Telegram / A2A.
This script pushes that copy: laptop → VPS.

What it syncs (from your local jobagent folder):
  - data/jobagent.db            (the CRM — always)
  - profile.json                (candidate profile — first time)
  - config.local.json           (only if you have one)

How it works (works on stock Windows + Mac + Linux — no rsync needed):
  1. Safe SQLite export (VACUUM INTO) so the live DB is never corrupted.
  2. Transfer via tar-over-SSH (built-in on Win10+/macOS/Linux).
  3. Triggers the VPS receive hook (validates, atomic-swap, restarts gateway).

Requirements:
  - Python 3.8+  (any: Anaconda, py, python)
  - Windows 10+ OpenSSH client (ssh/scp in System32 — usually pre-installed)
    Check: `ssh -V` in cmd. If missing: Settings → Apps → Optional Features → Add "OpenSSH Client".

Usage (from cmd/PowerShell/Git Bash — python resolves ssh from PATH):
  python scripts\\sync_to_vps.py --jobagent-dir . --ssh-key %USERPROFILE%\\.ssh\\id_ed25519
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

VPS_INCOMING = "/root/jobagent/sync/incoming"       # staging dir on the VPS
VPS_HOOK = "/root/jobagent/scripts/vps_receive_hook.sh"
HOME = Path.home()
DEFAULT_KEY_CANDIDATES = [
    HOME / ".ssh" / "id_ed25519",
    HOME / ".ssh" / "id_rsa",
    HOME / ".ssh" / "jobagent_sync_ed25519",
]


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run(cmd: list[str], dry: bool = False, timeout: int = 300, check_out: bool = True) -> subprocess.CompletedProcess:
    """Run a command, returning the result. On Windows, no shell needed since
    ssh/scp/tar are real .exe files (works from cmd too)."""
    log("$ " + " ".join(str(c) for c in cmd))
    if dry:
        return subprocess.CompletedProcess(cmd, 0)
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        if check_out:
            log(f"❌ executable not found: {e.filename}; is OpenSSH client installed? (try `ssh -V`)")
            sys.exit(1)
        raise


def sqlite_export(src: Path, dst: Path) -> bool:
    """VACUUM INTO a temp copy — safe even while the app is running."""
    if not src.exists():
        return False
    try:
        con = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=15)
        # Windows note: avoid concurrency errors on the live DB — VACUUM INTO
        # produces a consistent snapshot regardless of app activity.
        con.execute("VACUUM INTO ?", (str(dst),))
        con.close()
        return dst.exists() and dst.stat().st_size > 0
    except Exception as e:
        log(f"⚠ sqlite export failed: {e}")
        return False


def resolve_key(arg: str) -> Path:
    """Resolve the user-supplied key path; support bare filenames (resolve in ~/.ssh) too."""
    if not arg:
        for c in DEFAULT_KEY_CANDIDATES:
            if c.exists():
                return c
        log("❌ no ssh key found (tried ~/.ssh/id_ed25519, id_rsa, jobagent_sync_ed25519)")
        sys.exit(1)
    p = Path(arg).expanduser()
    if not p.exists() and not p.parent.name:  # bare name like "id_ed25519"
        p = HOME / ".ssh" / p.name
    if not p.exists():
        log(f"❌ ssh key not found: {p}")
        sys.exit(1)
    return p


def transfer_via_tar(staging: Path, dest: str, key: Path, port: int, dry: bool) -> subprocess.CompletedProcess:
    """No-rsync transfer: tar the staging dir to a temp .tar file, then scp it
    to the VPS and untar remotely. Avoids fragile cross-process pipes (the
    threading error you saw) and works on stock Windows (bsdtar + scp)."""
    tar_cmd = shutil.which("tar") or "tar"
    scp_cmd = shutil.which("scp") or "scp"
    ssh_cmd = shutil.which("ssh") or "ssh"

    with tempfile.TemporaryDirectory(prefix="jobagent-tar-") as tmp:
        tar_file = Path(tmp) / "incoming.tar"
        make_tar = [tar_cmd, "-c", "-f", str(tar_file), "-C", str(staging), "."]
        if dry:
            log("$ " + " ".join(make_tar))
            return subprocess.CompletedProcess(make_tar, 0)
        r = run(make_tar, dry, check_out=False)
        if r.returncode != 0:
            return r

        remote_tar = f"{VPS_INCOMING}/incoming.tar"
        scp_cmd_full = [
            scp_cmd, "-i", str(key), "-P", str(port),
            "-o", "StrictHostKeyChecking=accept-new",
            str(tar_file), f"{dest}:{remote_tar}",
        ]
        if dry:
            log("$ " + " ".join(scp_cmd_full))
            return subprocess.CompletedProcess(scp_cmd_full, 0)
        r2 = run(scp_cmd_full, dry, check_out=False)
        if r2.returncode != 0:
            return r2

        untar = [
            ssh_cmd, "-i", str(key), "-p", str(port),
            "-o", "StrictHostKeyChecking=accept-new", dest,
            f"mkdir -p {VPS_INCOMING} && tar -x -f {remote_tar} -C {VPS_INCOMING} && rm -f {remote_tar}",
        ]
        return run(untar, dry, check_out=False)


def transfer_via_rsync(staging: Path, dest: str, key: Path, port: int, dry_run: bool) -> subprocess.CompletedProcess:
    rsync = shutil.which("rsync")
    if not rsync:
        return transfer_via_tar(staging, dest, key, port, dry_run)
    cmd = ["rsync", "-avz", "--delete", "-e",
           f"ssh -i {key} -p {port} -o StrictHostKeyChecking=accept-new",
           f"{staging}/", f"{dest}:{VPS_INCOMING}/"]
    return run(cmd, dry_run)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="187.124.171.89")
    ap.add_argument("--user", default="root")
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--ssh-key", default="", help="path to private key (bare name OK, resolved in ~/.ssh)")
    ap.add_argument("--jobagent-dir", default=".", help="local jobagent checkout")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ja = Path(args.jobagent_dir).expanduser()
    if not (ja / "data" / "jobagent.db").exists():
        log(f"❌ no jobagent.db at {ja}/data/jobagent.db — point --jobagent-dir at your local repo")
        sys.exit(1)

    key = resolve_key(args.ssh_key)
    dest = f"{args.user}@{args.host}"
    log(f"➤ key: {key}")

    with tempfile.TemporaryDirectory(prefix="jobagent-sync-") as tmp:
        staging = Path(tmp) / "incoming"
        staging.mkdir()

        if sqlite_export(ja / "data" / "jobagent.db", staging / "jobagent.db"):
            log(f"✓ exported DB ({staging / 'jobagent.db'})")
        else:
            log("❌ could not export DB")
            sys.exit(1)

        for extra in ("profile.json", "config.local.json"):
            p = ja / extra
            if p.exists():
                shutil.copy2(p, staging / extra)
                log(f"✓ including {extra}")

        # 2. Transfer (rsync if available, else tar-over-ssh — always works on stock Windows)
        if shutil.which("rsync"):
            r = transfer_via_rsync(staging, dest, key, args.port, args.dry_run)
        else:
            r = transfer_via_tar(staging, dest, key, args.port, args.dry_run)
        if r.returncode != 0 and not args.dry_run:
            log("❌ transfer failed: " + (r.stderr or r.stdout or "")[-500:])
            sys.exit(1)

        # 3. Trigger the VPS receive hook (validates, swaps, restarts gateway)
        hook = ["ssh", "-i", str(key), "-p", str(args.port),
                "-o", "StrictHostKeyChecking=accept-new", dest,
                f"bash {VPS_HOOK} pc-inbox"]
        r2 = run(hook, args.dry_run)
        if r2.returncode != 0 and not args.dry_run:
            log("❌ hook failed: " + (r2.stderr or r2.stdout or "")[-400:])
            sys.exit(1)

    if args.dry_run:
        log("(dry-run — nothing pushed)")
    else:
        log("✅ sync complete — phone/TG now sees the fresh DB")


if __name__ == "__main__":
    main()
# JobAgent — Local PC ↔ VPS Data Sync (phone mirror)

> **One-way push: local PC → VPS.** No merging. Your VPS can't reach your
> email/Outlook, so it only holds a **copy** of your data so you can query
> JobAgent from your phone (`/jobagent` on Telegram, or any A2A parent).
> Pushing replaces the VPS copy with yours (previous copy auto-backed-up).

---

## TL;DR (once SSH key is set up)

```bash
# on your PC, inside your jobagent checkout (cmd / PowerShell / Git Bash all work)
python scripts\sync_to_vps.py --jobagent-dir . --ssh-key %USERPROFILE%\.ssh\id_ed25519
```

That's it — it exports your live DB safely, transfers it (rsync if you have it,
**otherwise tar-over-SSH which works on stock Windows 10+**), and the VPS
hook validates + swaps + restarts the gateway automatically.

---

## 1. One-time setup on your PC

### 1a. Install tools
- **Windows 10/11**: OpenSSH client is built in (Settings → Apps → Optional Features →
  add "OpenSSH Client" if `ssh -V` fails). Python from Anaconda/py works fine.
- **macOS / Linux**: ssh + tar are built in.

### 1b. SSH key pair
```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N "" -C "pc-jobagent-sync"
```

### 1c. Authorize the key on the VPS
Either:
- **From your PC** (copy the `.pub` content, one-shot with password if enabled):
  ```bash
  ssh-copy-id -i ~/.ssh/id_ed25519.pub root@187.124.171.89
  ```
- **Or paste into the VPS** (`~/.ssh/authorized_keys`) — put your public key on a
  new line. (A key `jobagent_sync_ed25519` already exists on the VPS + is
  authorized if you prefer to download the private half — NOT recommended to
  move private keys; generate your own.)

Verify:
```bash
ssh -i ~/.ssh/id_ed25519 root@187.124.171.89 "echo OK && hostname"
# → OK
```

### 1d. (Optional) Check rsync — only needed if you want delta transfer
If `rsync` is on PATH (Git Bash), the script uses it automatically. Otherwise it
falls back to tar-over-SSH — slower for big changes but zero extra installs.

```bash
# optional self-test with Git Bash only
rsync -avz -e "ssh -i ~/.ssh/id_ed25519" /c/Users/you/.ssh/ root@187.124.171.89:/tmp/rsync_self_test/
```

---

## 2. Run a sync

```bash
cd /path/to/jobagent   # your local checkout (must have data/jobagent.db + profile.json)
python scripts/sync_to_vps.py \
  --jobagent-dir "$PWD" \
  --host 187.124.171.89 --user root \
  --ssh-key ~/.ssh/id_ed25519
```

### What it pushes
| File | When |
|---|---|
| `data/jobagent.db` | always — **safe VACUUM INTO export** (works even while app runs) |
| `profile.json` | first time (VPS has none) — never overwrites an existing VPS profile |
| `config.local.json` | first time only, if you have one |

### Safety
- **No corruption**: export via `VACUUM INTO`, and the VPS runs
  `PRAGMA integrity_check` + table sanity **before** swapping.
- **Rollback**: previous DB kept at `~/jobagent/sync/backups/jobagent_*.db` (last 3).
- **Atomic**: new DB moved into place, gateway restarted, health-checked.
- **Log**: `~/jobagent/sync/sync.log`.

---

## 3. What NOT to sync / why no merge
- **Archives & snapshots** (`data/archives/*`, `data/snapshots/*`) are generated
  locally by the browser extension; syncing them is optional (they're plain
  files — just add them to the rsync list if you want them on the phone too).
- **Outlook/Gmail credentials** stay local. The VPS only answers queries about
  the copied CRM; it never contacts your inbox.
- Conflicts are impossible by design: the VPS copy is *replaced*, never merged.

---

## 4. Optional: automatic sync after each jobagent write
On your PC, add a post-hook to your local scripts (e.g. after the extension
archives a posting):
```bash
# in your local run script / cron / task scheduler:
python scripts/sync_to_vps.py --jobagent-dir "$PWD" --ssh-key ~/.ssh/id_ed25519
```
Or Windows Task Scheduler: run daily / hourly.

---

## 5. Restore / rollback on the VPS (if ever needed)
```bash
ssh root@187.124.171.89
cd /root/jobagent/sync/backups
ls -1t jobagent_*.db
cp jobagent_<stamp>.db /root/jobagent/data/jobagent.db
pm2 restart jobagent-a2a --update-env
```

## 6. Status check
```bash
ssh root@187.124.171.89 tail -20 /root/jobagent/sync/sync.log
```

---

## Files involved
| Path | Role |
|---|---|
| `/root/jobagent/scripts/sync_to_vps.py` | PC-side push script |
| `/root/jobagent/scripts/vps_receive_hook.sh` | VPS-side receive (validate, swap, restart) |
| `/root/jobagent/sync/incoming/` | rsync staging (drained after each sync) |
| `/root/jobagent/sync/backups/` | last 3 DB copies |
| `/root/jobagent/sync/sync.log` | audit log |
| `/root/.ssh/jobagent_sync_ed25519(.pub)` | convenience key created on VPS (VPS-internal test) |
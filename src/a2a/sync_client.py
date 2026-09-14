import io
import os
import zipfile
import urllib.request
import urllib.error
import json
from pathlib import Path

class JobAgentSyncClient:
    def __init__(self, target_url: str, token: str):
        self.target_url = target_url.rstrip("/")
        self.token = token

    def _create_zip_buffer(self) -> io.BytesIO:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. Archive the data directory
            data_dir = Path("data")
            if data_dir.exists() and data_dir.is_dir():
                for root, _, files in os.walk(data_dir):
                    for file in files:
                        # Don't backup journals to avoid locking issues
                        if file.endswith("-journal") or file.endswith("-wal") or file.endswith("-shm"):
                            continue
                        
                        file_path = Path(root) / file
                        arcname = str(file_path)
                        zf.write(file_path, arcname=arcname)
            
            # 2. Archive the local profile
            profile_path = Path("profile.local.json")
            if profile_path.exists():
                zf.write(profile_path, arcname=profile_path.name)
        
        buf.seek(0)
        return buf

    def push_to_vps(self) -> bool:
        print(f"[*] Packaging local data for secure transfer to {self.target_url}...")
        
        if not self.target_url.startswith("https://") and not self.target_url.startswith("http://localhost") and not self.target_url.startswith("http://127.0.0.1"):
            print("[!] WARNING: Target URL is not HTTPS and not localhost. Transmission is insecure!")
            
        zip_buf = self._create_zip_buffer()
        size_mb = len(zip_buf.getvalue()) / (1024 * 1024)
        print(f"[*] Payload size: {size_mb:.2f} MB")
        
        req = urllib.request.Request(
            f"{self.target_url}/a2a/v1/sync/push",
            data=zip_buf.getvalue(),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/zip"
            },
            method="POST"
        )
        
        try:
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    print(f"[+] Sync successful! VPS reported: {data.get('status', 'OK')}")
                    return True
                else:
                    print(f"[-] Sync failed with status: {response.status}")
                    return False
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="ignore")
            print(f"[-] HTTP Error {e.code}: {err_msg}")
            return False
        except urllib.error.URLError as e:
            print(f"[-] Network Error: Failed to reach {self.target_url}. Reason: {e.reason}")
            return False
        except Exception as e:
            print(f"[-] Unexpected Error: {e}")
            return False

"""Model Context Protocol (MCP) Stdio JSON-RPC client."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_GLOBAL_CLIENT: Optional[McpClient] = None
_CLIENT_LOCK = threading.Lock()


class McpClient:
    """Client communicating with an MCP server process over standard I/O (JSON-RPC 2.0)."""

    def __init__(self, command: Optional[List[str]] = None):
        if command:
            self.command = command
        else:
            # Default to @marlinjai/email-mcp via npx
            if os.name == "nt":
                self.command = ["cmd", "/c", "npx", "-y", "@marlinjai/email-mcp"]
            else:
                self.command = ["npx", "-y", "@marlinjai/email-mcp"]

        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._msg_id = 0
        self._cached_account_id: Optional[str] = None
        self._initialized = False

    def _ensure_process(self) -> bool:
        if self._process and self._process.poll() is None and self._initialized:
            return True

        try:
            log.info("Spawning MCP server process: %s", " ".join(self.command))
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )

            # JSON-RPC 2.0 initialize handshake
            init_req = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "jobagent-mcp-client", "version": "1.0.0"},
                },
            }
            init_resp = self._send_and_recv(init_req, timeout=15)
            if not init_resp or "result" not in init_resp:
                log.warning("MCP initialize handshake failed: %s", init_resp)
                self.close()
                return False

            # Initialized notification
            notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            self._send(notif)
            self._initialized = True
            log.info("MCP server initialized successfully")
            return True

        except Exception as e:
            log.warning("Failed to start MCP server process: %s", e)
            self.close()
            return False

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def _send(self, payload: Dict[str, Any]) -> None:
        if not self._process or not self._process.stdin:
            return
        line = json.dumps(payload) + "\n"
        self._process.stdin.write(line)
        self._process.stdin.flush()

    def _send_and_recv(self, payload: Dict[str, Any], timeout: int = 20) -> Optional[Dict[str, Any]]:
        self._send(payload)
        if not self._process or not self._process.stdout:
            return None

        line = self._process.stdout.readline()
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            log.debug("MCP raw output decode error: %s (line: %r)", exc, line[:200])
            return None

    def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        """Executes a tool on the MCP server and returns the unmarshalled content."""
        args = dict(arguments or {})

        with self._lock:
            if not self._ensure_process():
                raise RuntimeError(f"MCP server unavailable for tool '{tool_name}'")

            # Auto-resolve accountId for email tools if not provided
            if tool_name.startswith("email_") and "accountId" not in args:
                if not self._cached_account_id:
                    self._cached_account_id = self._resolve_primary_account_id()
                if self._cached_account_id:
                    args["accountId"] = self._cached_account_id

            req = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": args,
                },
            }

            resp = self._send_and_recv(req)
            if not resp:
                raise RuntimeError(f"Empty response from MCP server for tool '{tool_name}'")

            if "error" in resp:
                raise RuntimeError(f"MCP tool '{tool_name}' error: {resp['error']}")

            res_obj = resp.get("result", {})
            content = res_obj.get("content", [])
            if content and isinstance(content, list):
                first_block = content[0]
                text_content = first_block.get("text", "")
                try:
                    return json.loads(text_content)
                except (json.JSONDecodeError, TypeError):
                    return text_content

            return res_obj

    def _resolve_primary_account_id(self) -> Optional[str]:
        """Discovers configured account id via email_list_accounts."""
        try:
            req = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {
                    "name": "email_list_accounts",
                    "arguments": {},
                },
            }
            resp = self._send_and_recv(req)
            if resp and "result" in resp:
                content = resp["result"].get("content", [])
                if content:
                    accounts_data = json.loads(content[0].get("text", "[]"))
                    if isinstance(accounts_data, list) and len(accounts_data) > 0:
                        account_id = accounts_data[0].get("id")
                        log.info("Discovered primary MCP email accountId: %s (%s)", account_id, accounts_data[0].get("email"))
                        return account_id
        except Exception as e:
            log.warning("Could not auto-resolve MCP email accountId: %s", e)
        return None

    def close(self) -> None:
        """Closes the subprocess cleanly."""
        self._initialized = False
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None


def get_mcp_client() -> Optional[McpClient]:
    """Returns a shared McpClient instance, or None if npx is not available."""
    global _GLOBAL_CLIENT
    with _CLIENT_LOCK:
        if _GLOBAL_CLIENT is not None:
            return _GLOBAL_CLIENT

        if not shutil.which("npx") and not shutil.which("npx.cmd"):
            log.debug("npx not available on PATH; MCP client disabled")
            return None

        try:
            client = McpClient()
            if client._ensure_process():
                _GLOBAL_CLIENT = client
                return _GLOBAL_CLIENT
            else:
                client.close()
                return None
        except Exception as e:
            log.warning("Failed to initialize global MCP client: %s", e)
            return None

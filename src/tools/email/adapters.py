"""Multi-protocol email adapters for JobAgent.

Supports:
1. OutlookDesktopAdapter (headless MAPI inspection via pywin32)
2. ImapAdapter (Generic IMAP, ProtonMail Bridge, iCloud, Fastmail)
3. MockEmailAdapter (Synthetic emails for automated testing and CI)
"""

from __future__ import annotations

import email
import email.utils
import imaplib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.header import decode_header
from typing import Any, Dict, List, Optional, Union
from src.utils.date_utils import parse_flexible_date

log = logging.getLogger(__name__)


def _parse_flexible_iso(date_input: Optional[Any]) -> Optional[str]:
    """Parses flexible input to a YYYY-MM-DD string (or None)."""
    if not date_input:
        return None
    try:
        parsed = parse_flexible_date(date_input)
    except Exception as e:
        log.debug("Date could not be parsed %r: %s", date_input, e)
        return None
    if not parsed:
        return None
    # parse_flexible_date accepts datetimes/dates and ISO/dotted strings;
    # defensively normalize the result to a YYYY-MM-DD string.
    result = parsed
    if not isinstance(result, str):
        result = result.strftime("%Y-%m-%d")
    return result[:10]


def _to_imap_date(iso_date: Optional[str]) -> Optional[str]:
    """Converts YYYY-MM-DD to IMAP SEARCH date format dd-Mon-yyyy (e.g. 01-Sep-2026)."""
    if not iso_date:
        return None
    try:
        dt = datetime.strptime(iso_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    # IMAP date format is dd-Mon-yyyy with English month abbreviations
    return dt.strftime("%d-%b-%Y")


def build_imap_search_criteria(
    start_date: Optional[Any] = None,
    end_date: Optional[Any] = None,
    cutoff_date: Optional[Any] = None,
) -> List[str]:
    """Builds IMAP SEARCH criteria from flexible date inputs.

    Returns a list of IMAP search keys (e.g. ['SINCE 01-Sep-2026', 'BEFORE 08-Sep-2026'])
    fed to ``server.search(imap_criteria, 'ALL')``.

    - start+end -> ``SINCE <start> BEFORE <end>``
    - None/None -> ``ALL``
    - cutoff only -> ``SINCE <cutoff>``
    - Parsing failures are silently dropped (the client-side cutoff filter remains a second guard).
    """
    start_iso = _parse_flexible_iso(start_date) or _parse_flexible_iso(cutoff_date)
    end_iso = _parse_flexible_iso(end_date)

    start_imap = _to_imap_date(start_iso)
    end_imap = _to_imap_date(end_iso)

    criteria: List[str] = []
    if start_imap:
        criteria.append(f"SINCE {start_imap}")
    if end_imap:
        criteria.append(f"BEFORE {end_imap}")
    if not criteria:
        criteria.append("ALL")
    return criteria


def _decode_mime_str(header_val: str) -> str:
    """Safely decodes RFC 2047 MIME encoded words in email headers."""
    if not header_val:
        return ""
    try:
        decoded_chunks = decode_header(header_val)
        parts = []
        for chunk, encoding in decoded_chunks:
            if isinstance(chunk, bytes):
                parts.append(chunk.decode(encoding or "utf-8", errors="ignore"))
            else:
                parts.append(str(chunk))
        return "".join(parts)
    except Exception:
        return str(header_val)


@dataclass
class EmailRecord:
    entry_id: str
    sender_name: str
    sender_email: str
    subject: str
    received_time: str
    body: str
    preview: str = ""
    attachments: List[str] = field(default_factory=list)


class BaseEmailAdapter:
    def fetch_emails(
        self,
        cutoff_date: Optional[datetime] = None,
        start_date: Optional[Union[datetime, str]] = None,
        end_date: Optional[Union[datetime, str]] = None,
        limit: Optional[int] = None,
    ) -> List[EmailRecord]:
        raise NotImplementedError


class MockEmailAdapter(BaseEmailAdapter):
    """Adapter providing synthetic fixture emails for deterministic testing."""

    def __init__(self, mock_emails: Optional[List[Dict[str, Any]]] = None):
        self.mock_emails = mock_emails or []

    def set_mock_emails(self, emails: List[Dict[str, Any]]) -> None:
        self.mock_emails = emails

    def fetch_emails(
        self,
        cutoff_date: Optional[datetime] = None,
        start_date: Optional[Union[datetime, str]] = None,
        end_date: Optional[Union[datetime, str]] = None,
        limit: Optional[int] = None,
    ) -> List[EmailRecord]:
        start_str = parse_flexible_date(start_date) if start_date else None
        end_str = parse_flexible_date(end_date) if end_date else None
        cutoff_str = parse_flexible_date(cutoff_date) if cutoff_date else None
        if cutoff_str and not start_str:
            start_str = cutoff_str

        records: List[EmailRecord] = []
        for e in self.mock_emails:
            rec_time = e.get("received_time", datetime.now(timezone.utc).isoformat())
            rec_day = str(rec_time)[:10]
            if end_str and rec_day > end_str:
                continue
            if start_str and rec_day < start_str:
                continue

            records.append(
                EmailRecord(
                    entry_id=e.get("entry_id", f"mock_{len(records)}"),
                    sender_name=e.get("sender_name", ""),
                    sender_email=e.get("sender_email", ""),
                    subject=e.get("subject", ""),
                    received_time=rec_time,
                    body=e.get("body", ""),
                    preview=e.get("preview", e.get("body", "")[:150]),
                    attachments=e.get("attachments", []),
                )
            )
            if limit and len(records) >= limit:
                break
        return records


class OutlookDesktopAdapter(BaseEmailAdapter):
    """Inspects desktop Outlook folders via MAPI COM interface."""

    def __init__(self, folder_names: Optional[List[str]] = None):
        self.folder_names = folder_names or ["Bewerbung", "Inbox"]

    def _extract_sender_email(self, item: Any) -> str:
        sender_email = getattr(item, "SenderEmailAddress", "") or ""
        try:
            if getattr(item, "SenderEmailType", "") == "EX":
                sender_ex = item.Sender.GetExchangeUser()
                if sender_ex and sender_ex.PrimarySmtpAddress:
                    return sender_ex.PrimarySmtpAddress
        except Exception as e:
            log.debug("Could not resolve Exchange SMTP address: %s", e)
        return sender_email

    def fetch_emails(
        self,
        cutoff_date: Optional[datetime] = None,
        start_date: Optional[Union[datetime, str]] = None,
        end_date: Optional[Union[datetime, str]] = None,
        limit: Optional[int] = None,
    ) -> List[EmailRecord]:
        if sys.platform != "win32":
            log.debug("OutlookDesktopAdapter only supported on Windows")
            return []

        try:
            import win32com.client
            outlook = win32com.client.Dispatch("Outlook.Application")
            mapi = outlook.GetNamespace("MAPI")
        except Exception as e:
            log.info("Outlook desktop client not accessible: %s", e)
            return []

        start_str = parse_flexible_date(start_date) if start_date else None
        end_str = parse_flexible_date(end_date) if end_date else None
        cutoff_str = parse_flexible_date(cutoff_date) if cutoff_date else None
        if cutoff_str and not start_str:
            start_str = cutoff_str

        records: List[EmailRecord] = []
        target_folders: List[Any] = []

        # Find folders matching folder_names across all accounts
        for i in range(1, mapi.Folders.Count + 1):
            account = mapi.Folders.Item(i)
            for j in range(1, account.Folders.Count + 1):
                f = account.Folders.Item(j)
                for target_name in self.folder_names:
                    if f.Name.lower() == target_name.lower():
                        target_folders.append(f)

        for folder in target_folders:
            try:
                items = folder.Items
                items.Sort("[ReceivedTime]", True)
                for item in items:
                    if getattr(item, "Class", None) != 43:  # olMail
                        continue

                    rec_time = getattr(item, "ReceivedTime", None)
                    if not rec_time:
                        continue

                    rec_iso = rec_time.isoformat() if hasattr(rec_time, "isoformat") else str(rec_time)
                    rec_day = rec_iso[:10]

                    # Filter by date range (items are sorted descending)
                    if end_str and rec_day > end_str:
                        continue
                    if start_str and rec_day < start_str:
                        break

                    subject = getattr(item, "Subject", "") or ""
                    body = getattr(item, "Body", "") or ""
                    sender_name = getattr(item, "SenderName", "") or ""
                    sender_email = self._extract_sender_email(item)
                    entry_id = getattr(item, "EntryID", "") or f"outlook_{len(records)}"

                    clean_preview = " ".join(body.split())[:200]
                    records.append(
                        EmailRecord(
                            entry_id=entry_id,
                            sender_name=sender_name,
                            sender_email=sender_email,
                            subject=subject,
                            received_time=rec_iso,
                            body=body,
                            preview=clean_preview,
                        )
                    )
                    if limit and len(records) >= limit:
                        return records
            except Exception as e:
                log.warning("Outlook folder item iteration skipped due to error: %s", e)
                continue

        return records


class ImapAdapter(BaseEmailAdapter):
    """Connects to IMAP server using TLS/SSL."""

    def __init__(
        self,
        host: str,
        port: int = 993,
        username: str = "",
        password: str = "",
        use_ssl: bool = True,
        folder: str = "INBOX",
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.folder = folder

    def fetch_emails(
        self,
        cutoff_date: Optional[datetime] = None,
        start_date: Optional[Union[datetime, str]] = None,
        end_date: Optional[Union[datetime, str]] = None,
        limit: Optional[int] = None,
        **kwargs: Any,
    ) -> List[EmailRecord]:
        if not self.username or not self.password:
            log.warning("ImapAdapter skipped: missing username or password for host %s", self.host)
            return []

        records: List[EmailRecord] = []
        try:
            if self.use_ssl:
                server = imaplib.IMAP4_SSL(self.host, self.port)
            else:
                server = imaplib.IMAP4(self.host, self.port)
            server.login(self.username, self.password)
            server.select(self.folder, readonly=True)

            status, messages = server.search(build_imap_search_criteria(start_date, end_date, cutoff_date), "ALL")
            if status != "OK":
                return []

            msg_ids = messages[0].split()
            # Newest first
            msg_ids.reverse()

            if limit:
                msg_ids = msg_ids[:limit]

            for mid in msg_ids:
                res, data = server.fetch(mid, "(RFC822)")
                if res != "OK" or not data or not data[0]:
                    continue

                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)

                # Decode subject
                subject = _decode_mime_str(msg.get("Subject", ""))

                # Parse sender name and email
                raw_from = _decode_mime_str(msg.get("From", ""))
                s_name, s_email = email.utils.parseaddr(raw_from)
                sender_name = s_name if s_name else (s_email or raw_from)
                sender_email = s_email if s_email else raw_from

                # Parse Date header
                date_str = msg.get("Date", "")
                received_time = ""
                if date_str:
                    try:
                        parsed_dt = email.utils.parsedate_to_datetime(date_str)
                        if parsed_dt.tzinfo is None:
                            parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
                        if cutoff_date:
                            cutoff_aware = (
                                cutoff_date.replace(tzinfo=timezone.utc)
                                if cutoff_date.tzinfo is None
                                else cutoff_date
                            )
                            if parsed_dt < cutoff_aware:
                                continue
                        received_time = parsed_dt.isoformat()
                    except Exception as e:
                        log.debug("Failed parsing RFC 2822 Date '%s': %s", date_str, e)

                if not received_time:
                    received_time = datetime.now(timezone.utc).isoformat()

                body_text = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                body_text += payload.decode("utf-8", errors="ignore")
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body_text = payload.decode("utf-8", errors="ignore")

                # Stable Message-ID extraction
                raw_msg_id = msg.get("Message-ID", "").strip()
                if raw_msg_id:
                    entry_id = raw_msg_id.strip("<>")
                else:
                    entry_id = f"imap_{mid.decode('utf-8', errors='ignore')}"

                records.append(
                    EmailRecord(
                        entry_id=entry_id,
                        sender_name=sender_name,
                        sender_email=sender_email,
                        subject=subject,
                        received_time=received_time,
                        body=body_text,
                        preview=" ".join(body_text.split())[:200],
                    )
                )
            server.close()
            server.logout()
        except imaplib.IMAP4.error:
            log.warning("IMAP authentication or protocol error (credentials redacted)")
            return []
        except Exception as e:
            log.warning("IMAP fetch failed: %s", type(e).__name__)
            return []

        return records


class GmailMcpAdapter(BaseEmailAdapter):
    """Adapter that reads emails via the Gmail Model Context Protocol (MCP) server."""

    def __init__(self, mcp_client: Optional[Any] = None, search_query: Optional[str] = None):
        self.mcp_client = mcp_client
        if search_query is not None:
            self.search_query = search_query
        else:
            try:
                from src.core.config import load_config
                cfg = load_config()
                self.search_query = getattr(getattr(cfg, "email_ingestion", None), "gmail_search_query", "Bewerbung OR Interview OR Application")
            except Exception:
                self.search_query = "Bewerbung OR Interview OR Application"

    def fetch_emails(
        self,
        cutoff_date: Optional[datetime] = None,
        start_date: Optional[Union[datetime, str]] = None,
        end_date: Optional[Union[datetime, str]] = None,
        limit: Optional[int] = None,
        **kwargs: Any,
    ) -> List[EmailRecord]:
        records: List[EmailRecord] = []
        if not self.mcp_client:
            log.debug("No MCP client configured for GmailMcpAdapter; skipping")
            return records

        try:
            # Call MCP email_search
            search_res = self.mcp_client.call_tool("email_search", {"query": self.search_query, "limit": limit or 25})
            emails_data = json.loads(search_res) if isinstance(search_res, str) else search_res

            for msg in emails_data:
                raw_from = msg.get("from", "")
                s_name, s_email = email.utils.parseaddr(raw_from)
                sender_name = s_name if s_name else (s_email or raw_from)
                sender_email = s_email if s_email else raw_from

                records.append(
                    EmailRecord(
                        entry_id=msg.get("id", f"gmail_mcp_{len(records)}"),
                        sender_name=sender_name,
                        sender_email=sender_email,
                        subject=msg.get("subject", ""),
                        received_time=msg.get("date", datetime.now(timezone.utc).isoformat()),
                        body=msg.get("snippet", msg.get("body", "")),
                        preview=msg.get("snippet", "")[:200],
                    )
                )
        except Exception as e:
            log.warning("Gmail MCP search failed: %s", e, exc_info=True)

        return records


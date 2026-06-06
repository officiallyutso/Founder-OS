"""Inbox reading over IMAP (stdlib only).

Reuses the Gmail address + app password already configured for sending, so no new
credentials are needed. Reads recent messages WITHOUT marking them read (BODY.PEEK)
and returns clean, structured summaries. This is what lets the agent close the
outreach loop: see replies, match them to CRM contacts, and react.
"""
import email
import imaplib
import logging
from email.header import decode_header

from config import config

logger = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"


def is_configured() -> bool:
    return bool(config.gmail_address and config.gmail_app_password)


def _decode(value) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            try:
                out.append(text.decode(enc or "utf-8", errors="replace"))
            except Exception:
                out.append(text.decode("utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _body_snippet(msg, limit: int = 600) -> str:
    try:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True) or b""
                    return payload.decode(errors="replace").strip()[:limit]
            return ""
        payload = msg.get_payload(decode=True) or b""
        return payload.decode(errors="replace").strip()[:limit]
    except Exception:
        return ""


def fetch_recent(limit: int = 10, unread_only: bool = False) -> list:
    """Return recent inbox messages as dicts: from, subject, date, snippet."""
    if not is_configured():
        return [{"error": "Email reading not configured (need GMAIL_ADDRESS + GMAIL_APP_PASSWORD)."}]
    try:
        M = imaplib.IMAP4_SSL(IMAP_HOST)
        M.login(config.gmail_address, config.gmail_app_password)
        M.select("INBOX")
        criterion = "(UNSEEN)" if unread_only else "ALL"
        typ, data = M.search(None, criterion)
        ids = data[0].split()
        ids = ids[-limit:][::-1]  # most recent first
        out = []
        for mid in ids:
            typ, msg_data = M.fetch(mid, "(BODY.PEEK[])")  # PEEK = don't mark read
            if not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            out.append({
                "message_id": (msg.get("Message-ID") or "").strip(),
                "from": _decode(msg.get("From")),
                "subject": _decode(msg.get("Subject")),
                "date": msg.get("Date", ""),
                "snippet": _body_snippet(msg),
                "body": _body_snippet(msg, limit=2500),
            })
        M.logout()
        return out
    except Exception as e:
        logger.error(f"[email_reader] fetch failed: {e}")
        return [{"error": f"Could not read inbox: {e}"}]

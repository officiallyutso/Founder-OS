"""Email reply-tracking loop — closes the outreach loop.

Detects replies from CRM contacts in the inbox, logs them against the contact,
marks the contact as "responded", drafts a suggested reply with the LLM, and then
either auto-sends it (when autonomy is high) or surfaces it on Telegram with
one-tap Approve / Reject buttons. It also keeps a near-term follow-up scheduled
so conversations never go quiet.

Each reply is processed exactly once via a `seen_emails` dedupe table.
"""
import logging
from datetime import datetime, timedelta

from config import config
from agent import store

logger = logging.getLogger(__name__)


def _reply_subject(subject: str) -> str:
    s = (subject or "").strip()
    if not s:
        return "Re: your message"
    if s[:3].lower() == "re:":
        return s
    return f"Re: {s}"


def _msg_key(m: dict) -> str:
    """Stable identity for an email so we only ever process a reply once."""
    mid = (m.get("message_id") or "").strip()
    if mid:
        return mid
    return f"{m.get('from','')}|{m.get('subject','')}|{m.get('date','')}"


def _match_contact(frm: str, by_addr: dict, own: str):
    frm = (frm or "").lower()
    for addr, contact in by_addr.items():
        if addr and addr in frm and addr != own:
            return contact
    return None


async def _draft_reply(contact: dict, their_subject: str, their_message: str) -> str:
    from llm import router
    name = contact.get("name") or "there"
    company = contact.get("company") or ""
    sys = (
        f"You are {config.my_name}, {config.my_role} at {config.company_name}. "
        f"{config.my_one_liner}\n"
        "Write a concise, warm, professional reply to the email below.\n"
        "Rules: plain text only, NO subject line, 3-6 sentences, address them by first name, "
        f"and sign off as {config.my_name}. Do not invent facts, prices, dates, or commitments; "
        "if something needs the founder's decision, keep it open and offer to follow up."
    )
    usr = (
        f"Reply to {name}" + (f" at {company}" if company else "") + ".\n"
        f"Their subject: {their_subject}\n"
        f"Their message:\n{their_message}\n\n"
        "Write my reply body only."
    )
    body = await router.complete(
        [{"role": "system", "content": sys}, {"role": "user", "content": usr}],
        task_type="outreach", max_tokens=500,
    )
    return (body or "").strip()


async def _notify_reply(contact: dict, m: dict, draft: str, reply_subject: str,
                        auto: bool, record: dict):
    from scheduler import jobs as scheduler
    from agent import approvals

    name = contact.get("name") or "Contact"
    company = contact.get("company") or "?"
    snippet = (m.get("snippet") or "")[:600]
    header = (
        f"📩 *Reply from {name}* ({company})\n"
        f"*Subject:* {m.get('subject','')}\n\n"
        f"{snippet}"
    )

    if not draft:
        await scheduler.send_to_user(
            header + "\n\n_(I couldn't draft a reply automatically — ask me to write one.)_"
        )
        return

    full = f"{header}\n\n✍️ *Suggested reply:*\n{draft}"

    if auto:
        from agent import registry
        try:
            res = await registry.call("send_email", {
                "to_address": contact.get("email"),
                "subject": reply_subject,
                "body": draft,
                "contact_name": contact.get("name"),
            })
            ok = not (isinstance(res, dict) and (res.get("error") or res.get("success") is False))
        except Exception as e:
            logger.error(f"[reply_loop] auto-send failed: {e}")
            ok = False
        record["auto_sent"] = ok
        tag = "✅ *Auto-sent this reply.*" if ok else "⚠️ *Tried to auto-send but it failed — reply manually.*"
        await scheduler.send_to_user(f"{full}\n\n{tag}")
        return

    # Approval path: queue the send and surface it with one-tap buttons.
    q = approvals.enqueue("send_email", {
        "to_address": contact.get("email"),
        "subject": reply_subject,
        "body": draft,
        "contact_name": contact.get("name"),
    })
    aid = q.get("approval_id")
    record["approval_id"] = aid
    if aid:
        await scheduler.send_approval_to_user(aid, f"{full}\n\n_Tap Approve to send this reply._")
    else:
        await scheduler.send_to_user(f"{full}\n\n⚠️ {q.get('message', 'Could not queue the reply.')}")


async def process_replies(notify: bool = True, limit: int = 20) -> dict:
    """Scan the inbox for new replies from CRM contacts and close the loop on each."""
    from integrations import email_reader
    if not email_reader.is_configured():
        return {"configured": False, "processed": 0,
                "note": "Email reading not configured (set GMAIL_ADDRESS + GMAIL_APP_PASSWORD)."}

    from memory.sql_store import get_all_contacts, log_outreach, update_contact

    msgs = email_reader.fetch_recent(limit=limit, unread_only=False)
    if msgs and isinstance(msgs[0], dict) and msgs[0].get("error"):
        return {"configured": True, "processed": 0, "error": msgs[0]["error"]}

    own = (config.gmail_address or "").lower()
    by_addr = {(c.get("email") or "").lower(): c
               for c in get_all_contacts() if c.get("email")}

    processed = []
    for m in msgs:
        contact = _match_contact(m.get("from"), by_addr, own)
        if not contact:
            continue
        key = _msg_key(m)
        if store.email_seen(key):
            continue
        store.mark_email_seen(key)

        cid = contact["id"]
        subject = m.get("subject", "")
        body_in = m.get("body") or m.get("snippet") or ""

        try:
            log_outreach(cid, "email", "inbound", subject=subject,
                         body=body_in[:2000], status="received")
        except Exception as e:
            logger.error(f"[reply_loop] inbound log failed: {e}")

        # Mark as responded and keep the thread alive with a near-term follow-up.
        try:
            updates = {"next_followup_at": (datetime.now() + timedelta(days=3)).isoformat()}
            if (contact.get("status") or "") in ("", "prospect", "contacted", "new"):
                updates["status"] = "responded"
            update_contact(cid, **updates)
        except Exception as e:
            logger.error(f"[reply_loop] contact update failed: {e}")

        try:
            draft = await _draft_reply(contact, subject, body_in)
        except Exception as e:
            logger.error(f"[reply_loop] draft failed: {e}")
            draft = ""

        reply_subject = _reply_subject(subject)
        auto = bool(config.auto_approve or config.autonomy_level == "autonomous")

        record = {
            "contact": contact.get("name"), "company": contact.get("company"),
            "email": contact.get("email"), "subject": subject,
            "reply_subject": reply_subject, "drafted": bool(draft),
            "auto_sent": False, "approval_id": None,
        }

        if notify:
            try:
                await _notify_reply(contact, m, draft, reply_subject, auto, record)
            except Exception as e:
                logger.error(f"[reply_loop] notify failed: {e}")

        processed.append(record)

    return {"configured": True, "processed": len(processed), "replies": processed}

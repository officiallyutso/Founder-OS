import asyncio

import pytest

from agent import reply_loop, store
from memory import sql_store


def test_reply_subject():
    assert reply_loop._reply_subject("Re: hi") == "Re: hi"
    assert reply_loop._reply_subject("RE: hi") == "RE: hi"
    assert reply_loop._reply_subject("Quick question") == "Re: Quick question"
    assert reply_loop._reply_subject("") == "Re: your message"


def test_msg_key_prefers_message_id():
    assert reply_loop._msg_key({"message_id": "<a@b>"}) == "<a@b>"
    assert reply_loop._msg_key({"from": "x", "subject": "y", "date": "z"}) == "x|y|z"


def test_match_contact():
    by_addr = {"jane@acme.com": {"id": 1, "name": "Jane"}}
    assert reply_loop._match_contact("Jane <jane@acme.com>", by_addr, "me@x.com")["name"] == "Jane"
    assert reply_loop._match_contact("nope@other.com", by_addr, "me@x.com") is None
    # never match the founder's own address
    assert reply_loop._match_contact("me@x.com", {"me@x.com": {"id": 9}}, "me@x.com") is None


def test_process_replies_closes_loop(monkeypatch):
    cid = sql_store.add_contact(name="Jane", company="Acme", email="jane@acme.com", status="contacted")

    fake_msgs = [{
        "message_id": "<reply-1@acme.com>",
        "from": "Jane <jane@acme.com>",
        "subject": "Re: our chat",
        "date": "Mon, 1 Jan 2026 10:00:00 +0000",
        "snippet": "Sounds great, let's talk.",
        "body": "Sounds great, let's talk next week.",
    }]

    from integrations import email_reader
    monkeypatch.setattr(email_reader, "is_configured", lambda: True)
    monkeypatch.setattr(email_reader, "fetch_recent", lambda limit=20, unread_only=False: fake_msgs)

    async def fake_draft(contact, subject, body):
        return "Hi Jane, sounds good — next week works.\n\nUtso"

    monkeypatch.setattr(reply_loop, "_draft_reply", fake_draft)

    # balanced autonomy → queue an approval rather than auto-send
    from config import config
    monkeypatch.setattr(config, "auto_approve", False)
    monkeypatch.setattr(config, "autonomy_level", "balanced")

    res = asyncio.run(reply_loop.process_replies(notify=False))
    assert res["configured"] is True
    assert res["processed"] == 1
    rec = res["replies"][0]
    assert rec["contact"] == "Jane"
    assert rec["drafted"] is True

    # inbound logged + contact marked responded
    contact = sql_store.get_contact(cid)
    assert contact["status"] == "responded"
    assert contact["next_followup_at"] is not None

    # dedupe: second pass processes nothing new
    res2 = asyncio.run(reply_loop.process_replies(notify=False))
    assert res2["processed"] == 0

"""Perception tools — inbox, browser, and topic monitors."""
from agent.registry import register
from agent import store


@register(
    name="read_inbox",
    description="Read recent emails from the founder's inbox (does not mark them read). "
                "Use to check for replies, important messages, or context.",
    parameters={
        "type": "object",
        "properties": {
            "limit": {"type": "integer"},
            "unread_only": {"type": "boolean"},
        },
    },
    category="perception",
)
async def read_inbox(limit: int = 10, unread_only: bool = False):
    from integrations import email_reader
    return email_reader.fetch_recent(limit=limit, unread_only=unread_only)


@register(
    name="check_email_replies",
    description="Read the inbox and match senders against CRM contacts to spot replies "
                "from people you're in touch with. Returns matches with a snippet.",
    parameters={"type": "object", "properties": {}},
    category="perception",
)
async def check_email_replies():
    from integrations import email_reader
    from memory.sql_store import get_all_contacts
    msgs = email_reader.fetch_recent(limit=20, unread_only=False)
    if msgs and isinstance(msgs[0], dict) and msgs[0].get("error"):
        return msgs
    contacts = get_all_contacts()
    emails = {(c.get("email") or "").lower(): c for c in contacts if c.get("email")}
    matches = []
    for m in msgs:
        frm = (m.get("from") or "").lower()
        for addr, contact in emails.items():
            if addr and addr in frm:
                matches.append({
                    "contact": contact.get("name"), "company": contact.get("company"),
                    "subject": m.get("subject"), "snippet": m.get("snippet", "")[:300],
                })
    return matches or {"note": "No replies from known CRM contacts in recent inbox."}


@register(
    name="browse_page",
    description="Open a web page in a real headless browser and return its rendered text. "
                "Use for JavaScript-heavy pages where plain scraping fails.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
    category="perception",
)
async def browse_page(url: str):
    from integrations import browser
    return browser.fetch_rendered(url)


@register(
    name="add_monitor",
    description="Watch a topic over time. The agent periodically searches it and alerts the "
                "founder when genuinely new results appear (news, mentions, competitors).",
    parameters={
        "type": "object",
        "properties": {"topic": {"type": "string"}},
        "required": ["topic"],
    },
    category="perception",
)
async def add_monitor(topic: str):
    mid = store.add_monitor(topic)
    return {"monitor_id": mid, "topic": topic}


@register(
    name="list_monitors",
    description="List active topic monitors.",
    parameters={"type": "object", "properties": {}},
    category="perception",
)
async def list_monitors():
    return [{"id": m["id"], "topic": m["topic"]} for m in store.list_monitors()]


@register(
    name="remove_monitor",
    description="Stop watching a topic monitor by id.",
    parameters={
        "type": "object",
        "properties": {"monitor_id": {"type": "integer"}},
        "required": ["monitor_id"],
    },
    category="perception",
)
async def remove_monitor(monitor_id: int):
    store.deactivate_monitor(monitor_id)
    return {"removed": monitor_id}

"""Approval gate for risky / irreversible actions.

When the agentic loop hits a tool flagged `requires_approval` (and AUTO_APPROVE is
off), it calls `enqueue()` instead of executing. The user later replies
`approve <id>` or `reject <id>`; the bot routes that to `approve()` / `reject()`.
"""
import json
import logging

from agent import store, registry

logger = logging.getLogger(__name__)


def _summarize(tool_name: str, args: dict) -> str:
    if tool_name == "send_email":
        return f"Send email to {args.get('to_address')} — subject: \"{args.get('subject','')}\""
    if tool_name == "x_post":
        return f"Post to X: \"{(args.get('text') or '')[:120]}\""
    if tool_name == "calendar_delete_event":
        return f"Delete calendar event {args.get('event_id')}"
    if tool_name == "propose_code_change":
        return f"Record code-change proposal for {args.get('file')}"
    return f"{tool_name}({json.dumps(args)[:160]})"


def enqueue(tool_name: str, args: dict, risk_note: str = "") -> dict:
    summary = _summarize(tool_name, args)
    if risk_note:
        summary = f"{summary}\n   ⚠️ {risk_note}"
    aid = store.create_approval(tool_name, args, summary)
    return {
        "status": "pending_approval",
        "approval_id": aid,
        "summary": summary,
        "message": f"Queued for approval (id {aid}). Reply `approve {aid}` to do it, "
                   f"or `reject {aid}` to cancel.",
    }


def pending_text() -> str:
    rows = store.list_pending_approvals()
    if not rows:
        return "No pending approvals."
    lines = ["*Pending approvals:*"]
    for r in rows:
        lines.append(f"• `{r['id']}` — {r['summary']}")
    lines.append("\nReply `approve <id>` or `reject <id>`.")
    return "\n".join(lines)


async def approve(approval_id: int) -> str:
    appr = store.get_approval(approval_id)
    if not appr:
        return f"No approval with id {approval_id}."
    if appr["status"] != "pending":
        return f"Approval {approval_id} is already '{appr['status']}'."
    args = json.loads(appr["args_json"] or "{}")
    result = await registry.call(appr["tool_name"], args)
    ok = not (isinstance(result, dict) and (result.get("error") or result.get("success") is False))
    store.set_approval_status(approval_id, "executed" if ok else "failed", str(result)[:1000])
    store.log_action("user", appr["tool_name"], args, str(result)[:1000])
    if ok:
        return f"✅ Done: {appr['summary']}\n\n{_short(result)}"
    return f"⚠️ Tried but failed: {appr['summary']}\n\n{_short(result)}"


def reject(approval_id: int) -> str:
    appr = store.get_approval(approval_id)
    if not appr:
        return f"No approval with id {approval_id}."
    if appr["status"] != "pending":
        return f"Approval {approval_id} is already '{appr['status']}'."
    store.set_approval_status(approval_id, "rejected")
    return f"🚫 Rejected: {appr['summary']}"


def _short(result) -> str:
    if isinstance(result, dict):
        if result.get("htmlLink"):
            return result["htmlLink"]
        if result.get("url"):
            return result["url"]
        return json.dumps(result)[:300]
    return str(result)[:300]

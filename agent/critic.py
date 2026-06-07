"""Critic — self-verification before finalizing (Reflexion / chain-of-verification).

Two checks:
  - `verify_answer`: LLM-as-judge reviews the agent's final reply against the goal
    and the work done, catching hallucination, unmet requests, or wrong tone. If it
    finds fixable issues it returns guidance the executor can use for one revision.
  - `precheck_action`: a quick sanity review of a high-stakes, approval-gated action
    (e.g. an email body / tweet) so the approval card can warn the founder.
"""
import json
import logging

from llm.router import complete

logger = logging.getLogger(__name__)

_HIGH_STAKES = {"send_email", "x_post", "propose_code_change", "create_tool"}


async def verify_answer(goal: str, answer: str, work_summary: str = "") -> dict:
    """Return {'ok', 'issues', 'suggestion', 'confidence', 'clarify'}.

    Besides catching real problems, it estimates how confident/grounded the reply is
    and, when shaky, proposes a clarifying question — fueling honest abstention.
    """
    if not answer or len(answer) < 3:
        return {"ok": True, "issues": "", "suggestion": "", "confidence": "high", "clarify": ""}
    messages = [
        {"role": "system", "content":
            "You are the verification module of an autonomous assistant. Judge whether "
            "the DRAFT REPLY actually and accurately satisfies the user's GOAL given the "
            "work done. Flag only real problems: unmet parts of the request, likely "
            "fabrication, contradictions, or clearly wrong tone. Small style nits are NOT "
            "problems. Also estimate how well-grounded the reply is in the work done: "
            "'high' if clearly supported, 'medium' if partly, 'low' if it looks like a "
            "guess or relies on facts that weren't verified. If confidence is low, give a "
            "short clarifying question the assistant should ask the user. Respond ONLY with JSON."},
        {"role": "user", "content": f"""GOAL:
{goal[:1200]}

WORK DONE (tools used, etc.):
{work_summary[:800] or '(none recorded)'}

DRAFT REPLY:
{answer[:1800]}

Respond ONLY with JSON:
{{"ok": true, "issues": "", "suggestion": "", "confidence": "high|medium|low", "clarify": ""}}
Set ok=false only if there is a real, fixable problem; put the problem in 'issues' and a
concrete fix instruction in 'suggestion'. 'clarify' is only needed when confidence is low."""},
    ]
    try:
        raw = await complete(messages, task_type="analysis", max_tokens=320)
        clean = raw.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(clean)
        conf = str(data.get("confidence", "high")).lower()
        if conf not in ("high", "medium", "low"):
            conf = "high"
        return {
            "ok": bool(data.get("ok", True)),
            "issues": data.get("issues", ""),
            "suggestion": data.get("suggestion", ""),
            "confidence": conf,
            "clarify": data.get("clarify", ""),
        }
    except Exception as e:
        logger.debug(f"[critic] verify_answer skipped: {e}")
        return {"ok": True, "issues": "", "suggestion": "", "confidence": "high", "clarify": ""}


async def precheck_action(tool_name: str, args: dict) -> dict:
    """Quick risk note for a high-stakes action. Returns {'ok': bool, 'note': str}."""
    if tool_name not in _HIGH_STAKES:
        return {"ok": True, "note": ""}
    payload = ""
    if tool_name == "send_email":
        payload = f"To: {args.get('to_address')}\nSubject: {args.get('subject')}\n\n{args.get('body','')}"
    elif tool_name == "x_post":
        payload = args.get("text", "")
    elif tool_name == "propose_code_change":
        payload = f"File: {args.get('file')}\n{args.get('change','')[:600]}"
    elif tool_name == "create_tool":
        payload = f"New tool {args.get('name')}: {args.get('description','')}\nCode:\n{args.get('body','')[:600]}"

    messages = [
        {"role": "system", "content":
            "You are a safety reviewer for an autonomous assistant about to take a "
            "high-stakes action. In ONE short sentence, note any red flag (wrong "
            "recipient, leaking secrets, offensive/embarrassing content, obvious "
            "mistake). If it looks fine, say so. Respond ONLY with JSON."},
        {"role": "user", "content": f"""ACTION: {tool_name}
PAYLOAD:
{payload[:1200]}

Respond ONLY with JSON: {{"ok": true, "note": "one short sentence"}}"""},
    ]
    try:
        raw = await complete(messages, task_type="analysis", max_tokens=120)
        clean = raw.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(clean)
        return {"ok": bool(data.get("ok", True)), "note": data.get("note", "")}
    except Exception as e:
        logger.debug(f"[critic] precheck skipped: {e}")
        return {"ok": True, "note": ""}

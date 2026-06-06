"""Planner — turns a goal into an explicit, ordered plan before execution.

This implements the "plan-and-execute" pattern: for non-trivial requests the agent
first decomposes the goal into concrete steps. The plan is injected into the
executor's context as a working checklist and (optionally) persisted as a subtask
DAG so long-horizon work is inspectable and resumable.
"""
import json
import logging

from llm.router import complete
from agent import store

logger = logging.getLogger(__name__)

# Cheap heuristic: decide whether a turn deserves explicit planning at all.
_DELIBERATE_HINTS = (
    " and ", " then ", "plan", "research", "draft", "find ", "schedule",
    "every ", "all ", "outreach", "campaign", "compare", "analyze", "build",
    "list of", "each ", "multiple", "step by step",
)


def needs_planning(message: str) -> bool:
    m = (message or "").lower().strip()
    if m.startswith("[heartbeat]"):
        return True
    if len(m) > 140:
        return True
    hint_hits = sum(1 for h in _DELIBERATE_HINTS if h in m)
    return hint_hits >= 2


async def make_plan(goal: str, context: str = "", persist: bool = True) -> dict:
    """Return {'steps': [...], 'rationale': str, 'plan_id': int|None}."""
    messages = [
        {"role": "system", "content":
            "You are the planning module of an autonomous founder's-assistant agent. "
            "Decompose the goal into a SHORT ordered list of concrete, executable steps "
            "(prefer 2-6). Each step should map to something the agent can do with its "
            "tools (research, CRM, draft/send email, reminders, calendar, web search, "
            "memory, social drafts). Be concise. Respond ONLY with JSON."},
        {"role": "user", "content": f"""GOAL:
{goal}

CONTEXT (may be empty):
{context or '(none)'}

Respond ONLY with JSON:
{{
  "rationale": "one sentence on the approach",
  "steps": [
    {{"description": "step text", "depends_on": []}}
  ]
}}"""},
    ]
    try:
        raw = await complete(messages, task_type="analysis", max_tokens=500)
        clean = raw.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(clean)
    except Exception as e:
        logger.debug(f"[planner] failed, proceeding without plan: {e}")
        return {"steps": [], "rationale": "", "plan_id": None}

    steps = data.get("steps") or []
    rationale = data.get("rationale", "")
    plan_id = None
    if persist and steps:
        try:
            plan_id = store.create_plan(goal[:500], rationale, steps)
        except Exception as e:
            logger.debug(f"[planner] persist failed: {e}")
    return {"steps": steps, "rationale": rationale, "plan_id": plan_id}


def render_plan(plan: dict) -> str:
    """Render a plan as a checklist block for prompt injection."""
    steps = plan.get("steps") or []
    if not steps:
        return ""
    lines = []
    if plan.get("rationale"):
        lines.append(f"Approach: {plan['rationale']}")
    for i, s in enumerate(steps, 1):
        desc = s.get("description") if isinstance(s, dict) else str(s)
        lines.append(f"{i}. {desc}")
    return "\n".join(lines)

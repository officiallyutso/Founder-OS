"""Shared tool-calling executor loop.

Extracted so both the top-level AgentCore and delegated sub-agents run the exact
same execution semantics (tool calls, approval gating, action logging) over
whatever tool subset they're given.
"""
import json
import logging

from agent import registry, approvals, critic, policy, safety
from agent.store import log_action
from llm.tool_client import complete_with_tools

logger = logging.getLogger(__name__)

MAX_STEPS = 8


async def execute_loop(messages: list, schemas: list, actor: str = "agent",
                       on_status=None, tools_used: list = None,
                       max_steps: int = MAX_STEPS) -> str:
    """Run the tool-calling loop until the model returns a final answer."""
    tools_used = tools_used if tools_used is not None else []
    for _ in range(max_steps):
        try:
            resp = await complete_with_tools(messages, schemas)
        except Exception as e:
            logger.error(f"[loop] LLM call failed: {e}")
            return f"⚠️ My reasoning engine hit an error: {str(e)[:200]}"

        messages.append(resp["raw"])
        calls = resp.get("tool_calls") or []
        if not calls:
            return (resp.get("content") or "").strip()

        for tc in calls:
            name, args, call_id = tc["name"], tc["arguments"], tc["id"]
            tools_used.append(name)
            tool = registry.get(name)

            if on_status:
                try:
                    await on_status(f"⚙️ {name}…")
                except Exception:
                    pass

            if tool is None:
                result = {"error": f"Unknown tool: {name}"}
            else:
                decision = policy.decide(tool, args)
                if decision == "deny":
                    result = {"denied": f"Policy blocked '{name}'."}
                elif decision == "approve":
                    check = await critic.precheck_action(name, args)
                    note = "" if check.get("ok", True) else check.get("note", "")
                    result = approvals.enqueue(name, args, risk_note=note)
                else:
                    result = await registry.call(name, args)
                    log_action(actor, name, args, json.dumps(result, default=str)[:1500])
                    result = safety.wrap_tool_result(name, result)

            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps(result, default=str)[:6500],
            })
    return "I did a lot of work but didn't wrap up cleanly. Ask me to continue."

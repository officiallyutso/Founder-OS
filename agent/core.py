"""AgentCore — the agentic loop (plan -> execute -> verify).

The model is given the full tool catalog and decides what to call, chaining tools
until it can answer. For non-trivial goals it first drafts an explicit plan
(plan-and-execute), and before finalizing it self-verifies the answer
(Reflexion / chain-of-verification). Risky tools are intercepted for approval.
After notable turns an async reflection pass lets the agent learn.
"""
import asyncio
import json
import logging

from agent import registry, identity, evolution, approvals, planner, critic
import agent.tools  # noqa: F401 — importing registers every tool
from agent.store import log_action, set_plan_status
from llm.tool_client import complete_with_tools
from memory.vector_store import add as vec_add, search_all
from config import config

logger = logging.getLogger(__name__)

MAX_STEPS = 8
HISTORY_TURNS = 8  # how many prior (user/assistant) messages to carry

# Single authorized user → a module-level rolling transcript is fine.
_history = []


def _memory_context(message: str) -> str:
    try:
        hits = search_all(message, n_results=4)
    except Exception:
        return ""
    if not hits:
        return ""
    return "\n".join(f"- [{h['collection']}] {h['text'][:200]}" for h in hits)


async def _execute_loop(messages: list, schemas: list, actor: str, on_status,
                        tools_used: list, max_steps: int = MAX_STEPS) -> str:
    """Run the tool-calling loop until the model returns a final answer."""
    final_text = ""
    for _ in range(max_steps):
        try:
            resp = await complete_with_tools(messages, schemas)
        except Exception as e:
            logger.error(f"[core] LLM call failed: {e}")
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
            elif tool.requires_approval and not config.auto_approve:
                check = await critic.precheck_action(name, args)
                note = "" if check.get("ok", True) else check.get("note", "")
                result = approvals.enqueue(name, args, risk_note=note)
            else:
                result = await registry.call(name, args)
                log_action(actor, name, args, json.dumps(result, default=str)[:1500])

            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps(result, default=str)[:6000],
            })
    return final_text or "I did a lot of work but didn't wrap up cleanly. Ask me to continue."


async def run(user_message: str, image_context: str = "", actor: str = "user",
              on_status=None) -> str:
    """Process one user turn through plan -> execute -> verify and return the reply."""
    enriched = user_message
    if image_context:
        enriched += f"\n\n[IMAGE CONTENT]\n{image_context}"

    skills_block, lessons_block, goals_block = evolution.retrieve_context(user_message)
    system_prompt = identity.build_system_prompt(
        skills_block=skills_block,
        lessons_block=lessons_block,
        goals_block=goals_block,
        extra_context=_memory_context(user_message),
    )

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(_history[-HISTORY_TURNS:])

    # ── PLAN (only for non-trivial goals) ─────────────────────────────────────
    plan_id = None
    deliberate = planner.needs_planning(user_message)
    if deliberate:
        if on_status:
            try:
                await on_status("🧭 planning…")
            except Exception:
                pass
        try:
            plan = await planner.make_plan(user_message, context=goals_block)
            plan_id = plan.get("plan_id")
            rendered = planner.render_plan(plan)
            if rendered:
                messages.append({"role": "system",
                                 "content": "WORKING PLAN (follow it, adapt if needed):\n" + rendered})
        except Exception as e:
            logger.debug(f"[core] planning skipped: {e}")

    messages.append({"role": "user", "content": enriched})

    schemas = registry.all_schemas()
    tools_used = []

    # ── EXECUTE ────────────────────────────────────────────────────────────────
    final_text = await _execute_loop(messages, schemas, actor, on_status, tools_used)

    # ── VERIFY + one refinement (only for deliberate turns) ────────────────────
    if deliberate and final_text and not final_text.startswith("⚠️"):
        try:
            check = await critic.verify_answer(
                user_message, final_text, work_summary=", ".join(tools_used))
            if not check.get("ok", True) and check.get("suggestion"):
                if on_status:
                    try:
                        await on_status("🔍 self-checking…")
                    except Exception:
                        pass
                messages.append({"role": "assistant", "content": final_text})
                messages.append({"role": "user", "content":
                                 f"[SELF-CHECK] Problem found: {check.get('issues','')}. "
                                 f"{check.get('suggestion','')} Now give me the corrected final reply."})
                final_text = await _execute_loop(messages, schemas, actor, on_status,
                                                 tools_used, max_steps=3)
        except Exception as e:
            logger.debug(f"[core] verify skipped: {e}")

    if not final_text:
        final_text = "Done."

    if plan_id:
        try:
            set_plan_status(plan_id, "done")
        except Exception:
            pass

    # Persist the turn and roll history.
    _history.append({"role": "user", "content": enriched})
    _history.append({"role": "assistant", "content": final_text})
    del _history[: max(0, len(_history) - HISTORY_TURNS * 2)]

    try:
        vec_add("conversations", enriched, metadata={"role": "user"})
        vec_add("conversations", final_text, metadata={"role": "assistant"})
    except Exception:
        pass

    # Fire-and-forget self-evolution on substantive turns.
    if tools_used or len(user_message) > 40:
        asyncio.create_task(_safe_reflect(user_message, final_text, tools_used))

    return final_text


async def _safe_reflect(user_message, final_text, tools_used):
    try:
        await evolution.reflect(user_message, final_text, tools_used)
    except Exception as e:
        logger.debug(f"[core] reflection error: {e}")

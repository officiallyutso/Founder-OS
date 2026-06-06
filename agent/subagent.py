"""Specialist sub-agents (multi-agent orchestration).

The top-level agent acts as a SUPERVISOR: for a focused chunk of work it can hand
off to a specialist sub-agent that runs its own tool-calling loop with a narrowed
toolset and a role-specific brief. Sub-agents can run in parallel. This mirrors
the supervisor/handoff pattern (OpenAI Agents SDK / LangGraph / Swarm), implemented
locally with the shared executor loop.
"""
import asyncio
import logging

from agent import registry
from agent.loop import execute_loop
from config import config

logger = logging.getLogger(__name__)

# name -> spec. `categories` selects which tools the sub-agent may use.
SPECIALISTS = {
    "researcher": {
        "categories": {"research", "perception"},
        "brief": "You are a research specialist. Gather accurate, well-sourced information "
                 "using web search, scraping, browsing, and company research. Never invent "
                 "facts. Return a tight, structured findings summary.",
    },
    "outreach": {
        "categories": {"outreach", "crm"},
        "brief": "You are an outreach specialist. Draft sharp, personalized, concise "
                 "messages and manage CRM state. Sending stays approval-gated; produce the "
                 "draft and note the recipient.",
    },
    "ops": {
        "categories": {"tasks", "reminders", "calendar", "goals"},
        "brief": "You are an operations specialist. Handle scheduling, reminders, tasks, "
                 "calendar, and goal tracking precisely. Confirm concrete times/dates.",
    },
    "analyst": {
        "categories": {"research", "evolution"},
        "brief": "You are an analyst. Reason carefully over available information and the "
                 "founder's memory to produce clear judgments, comparisons, and recommendations.",
    },
}


def list_specialists() -> list:
    return list(SPECIALISTS.keys())


async def run_subagent(name: str, task: str, actor: str = "subagent") -> dict:
    spec = SPECIALISTS.get(name)
    if not spec:
        return {"error": f"Unknown specialist '{name}'. Options: {list_specialists()}"}

    system = (
        f"{spec['brief']}\n\n"
        f"You are a delegated sub-agent for {config.my_name} at {config.company_name}. "
        f"Focus ONLY on the task you are given, use your tools, and return a concise result "
        f"the supervisor can use directly. Do not chit-chat."
    )
    schemas = registry.schemas_for(spec["categories"])
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": task}]
    tools_used = []
    result = await execute_loop(messages, schemas, actor=f"subagent:{name}",
                                on_status=None, tools_used=tools_used, max_steps=6)
    return {"specialist": name, "result": result, "tools_used": tools_used}


async def run_parallel(tasks: list) -> list:
    """Run several {specialist, task} handoffs concurrently."""
    coros = [run_subagent(t.get("specialist", ""), t.get("task", "")) for t in tasks]
    return await asyncio.gather(*coros, return_exceptions=False)

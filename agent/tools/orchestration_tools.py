"""Orchestration tools — the supervisor delegating to specialist sub-agents."""
from agent.registry import register
from agent import subagent


@register(
    name="delegate",
    description="Hand off a focused task to a specialist sub-agent that has its own tools "
                "and runs its own loop. Specialists: 'researcher' (web/company research), "
                "'outreach' (drafting + CRM), 'ops' (tasks/reminders/calendar/goals), "
                "'analyst' (reasoning over info + memory). Use this to keep complex work "
                "organized and to go deep on one part without losing the thread.",
    parameters={
        "type": "object",
        "properties": {
            "specialist": {"type": "string", "enum": ["researcher", "outreach", "ops", "analyst"]},
            "task": {"type": "string", "description": "A clear, self-contained instruction."},
        },
        "required": ["specialist", "task"],
    },
    category="orchestration",
)
async def delegate(specialist: str, task: str):
    return await subagent.run_subagent(specialist, task)


@register(
    name="delegate_parallel",
    description="Run several specialist handoffs at once (parallel) and get all results. "
                "Great for fanning out independent work, e.g. research 3 companies at once.",
    parameters={
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "specialist": {"type": "string"},
                        "task": {"type": "string"},
                    },
                    "required": ["specialist", "task"],
                },
            },
        },
        "required": ["tasks"],
    },
    category="orchestration",
)
async def delegate_parallel(tasks: list):
    return await subagent.run_parallel(tasks)

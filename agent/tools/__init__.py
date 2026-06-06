"""Importing this package registers every tool with the registry.

Order doesn't matter; each module calls registry.register() at import time.
Optional-integration tools (calendar, social) import their heavy deps lazily
inside the tool body, so importing them here never crashes if a lib is missing.
"""
from agent.tools import (  # noqa: F401
    memory_tools,
    brain_tools,
    crm_tools,
    research_tools,
    task_tools,
    goal_tools,
    reminder_tools,
    outreach_tools,
    calendar_tools,
    social_tools,
    evolution_tools,
    meta_tools,
    optimizer_tools,
    perception_tools,
    orchestration_tools,
)

# Load any tools the agent authored for itself in past sessions.
from agent import skills_factory as _sf  # noqa: E402
_sf.load_generated()

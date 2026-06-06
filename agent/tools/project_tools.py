"""Durable project tools — long-horizon, resumable work.

Unlike the per-turn plan scaffold, a PROJECT persists across sessions: its steps
and their results are checkpointed in the DB so the agent (or the founder) can
pick it up days later exactly where it left off. Backed by the plans/subtasks
tables.
"""
from agent.registry import register
from agent import store


@register(
    name="start_project",
    description="Begin a durable, multi-session project with named steps. Persists so it can "
                "be resumed later. Use for work that spans days (e.g. a fundraising push, a "
                "hiring round, a launch).",
    parameters={
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "steps": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["goal", "steps"],
    },
    category="tasks",
)
async def start_project(goal: str, steps: list):
    plan_id = store.create_plan(goal, "durable project", [{"description": s} for s in steps])
    return {"project_id": plan_id, "goal": goal, "steps": steps}


@register(
    name="list_projects",
    description="List open durable projects and their progress.",
    parameters={"type": "object", "properties": {}},
    category="tasks",
)
async def list_projects():
    out = []
    for p in store.list_open_plans():
        if (p.get("rationale") or "") != "durable project":
            continue  # skip per-turn planning scaffolds
        full = store.get_plan(p["id"]) or {}
        subs = full.get("subtasks", [])
        done = sum(1 for s in subs if s.get("status") == "done")
        out.append({"project_id": p["id"], "goal": p["goal"],
                    "progress": f"{done}/{len(subs)} steps done"})
    return out or {"note": "No open projects."}


@register(
    name="project_status",
    description="Get the full step-by-step status of one project, including step results.",
    parameters={
        "type": "object",
        "properties": {"project_id": {"type": "integer"}},
        "required": ["project_id"],
    },
    category="tasks",
)
async def project_status(project_id: int):
    plan = store.get_plan(project_id)
    return plan or {"error": f"No project {project_id}."}


@register(
    name="advance_project",
    description="Mark a project step done and checkpoint its result, so progress survives "
                "across sessions.",
    parameters={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer"},
            "step_seq": {"type": "integer", "description": "0-based step index."},
            "result": {"type": "string"},
        },
        "required": ["project_id", "step_seq", "result"],
    },
    category="tasks",
)
async def advance_project(project_id: int, step_seq: int, result: str):
    plan = store.get_plan(project_id)
    if not plan:
        return {"error": f"No project {project_id}."}
    for s in plan.get("subtasks", []):
        if s.get("seq") == step_seq:
            store.update_subtask(s["id"], "done", result)
            remaining = [x for x in plan["subtasks"] if x.get("status") != "done" and x["id"] != s["id"]]
            if not remaining:
                store.set_plan_status(project_id, "done")
                return {"updated": True, "project_complete": True}
            return {"updated": True, "remaining_steps": len(remaining)}
    return {"error": f"No step {step_seq} in project {project_id}."}


@register(
    name="complete_project",
    description="Mark an entire project finished.",
    parameters={
        "type": "object",
        "properties": {"project_id": {"type": "integer"}},
        "required": ["project_id"],
    },
    category="tasks",
)
async def complete_project(project_id: int):
    store.set_plan_status(project_id, "done")
    return {"completed": project_id}


@register(
    name="agent_status",
    description="Report the agent's current operating status: autonomy level, today's LLM "
                "usage vs cap, and whether it's paused.",
    parameters={"type": "object", "properties": {}},
    category="meta",
)
async def agent_status():
    from agent import budget
    return budget.status()

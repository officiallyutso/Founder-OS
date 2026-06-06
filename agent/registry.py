"""Tool registry.

Tools are plain Python callables (sync or async) registered with an OpenAI-style
JSON schema. The agentic loop reads `all_schemas()` to tell the model what it can
do, and calls `call()` to actually run a tool.

Tools flagged `requires_approval=True` are not executed directly by the loop;
the loop enqueues an approval instead (see agent/approvals.py). The registry's
`call()` always performs the real action — approval bypassing is the loop's job.
"""
import asyncio
import inspect
import logging

logger = logging.getLogger(__name__)

_TOOLS = {}


class Tool:
    def __init__(self, name, description, parameters, func,
                 requires_approval=False, category="general"):
        self.name = name
        self.description = description
        self.parameters = parameters or {"type": "object", "properties": {}}
        self.func = func
        self.requires_approval = requires_approval
        self.category = category

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def register(name, description, parameters=None, requires_approval=False, category="general"):
    """Decorator to register a callable as an agent tool."""
    def deco(func):
        _TOOLS[name] = Tool(name, description, parameters, func,
                            requires_approval, category)
        return func
    return deco


def get(name) -> Tool:
    return _TOOLS.get(name)


def all_tools() -> list:
    return list(_TOOLS.values())


def all_schemas() -> list:
    return [t.schema() for t in _TOOLS.values()]


def schemas_for(categories) -> list:
    """Schemas for tools whose category is in `categories` (plus 'memory' always)."""
    allowed = set(categories) | {"memory"}
    return [t.schema() for t in _TOOLS.values() if t.category in allowed]


async def call(name: str, args: dict):
    """Execute a tool by name. Handles sync + async callables."""
    tool = _TOOLS.get(name)
    if tool is None:
        return {"error": f"Unknown tool: {name}"}
    args = args or {}
    try:
        if inspect.iscoroutinefunction(tool.func):
            return await tool.func(**args)
        # Run sync tools in a thread so blocking I/O doesn't stall the loop.
        return await asyncio.to_thread(lambda: tool.func(**args))
    except TypeError as e:
        return {"error": f"Bad arguments for {name}: {e}"}
    except Exception as e:
        logger.error(f"[registry] tool '{name}' raised: {e}")
        return {"error": f"Tool '{name}' failed: {e}"}

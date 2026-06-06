"""Self-knowledge tool: let the agent accurately describe itself and its maker."""
from agent.registry import register
from agent import about


@register(
    name="about_self",
    description="Describe yourself accurately: who built you (Utso, @officiallyutso), how "
                "complex/advanced you are, your architecture, and exactly what you can do. Call "
                "this whenever the founder asks who made/created you, what you are, how complex or "
                "advanced you are, or what your features/capabilities are — then summarize naturally.",
    parameters={"type": "object", "properties": {}},
    category="meta",
)
def about_self():
    return about.describe()

"""Chart generation tool: visualize metrics and send the image to the founder."""
from agent.registry import register


@register(
    name="generate_chart",
    description="Render a chart (bar/line/pie) from labels + values and send it to the founder as "
                "an image. Use to visualize metrics, pipeline, finances, growth, or comparisons. "
                "labels and values must be the same length.",
    parameters={
        "type": "object",
        "properties": {
            "labels": {"type": "array", "items": {"type": "string"}, "description": "Category/x-axis labels."},
            "values": {"type": "array", "items": {"type": "number"}, "description": "Numeric values, one per label."},
            "chart_type": {"type": "string", "enum": ["bar", "line", "pie"], "description": "Default bar."},
            "title": {"type": "string"},
        },
        "required": ["labels", "values"],
    },
    category="tasks",
)
async def generate_chart(labels, values, chart_type="bar", title=""):
    if not labels or not values or len(labels) != len(values):
        return {"error": "labels and values must be non-empty and the same length."}
    try:
        from agent import charts
        path = charts.render_chart(chart_type, labels, values, title)
    except ImportError:
        return {"error": "Charts need matplotlib installed (pip install matplotlib)."}
    except Exception as e:
        return {"error": f"Chart render failed: {e}"}
    from scheduler.jobs import send_photo_to_user
    delivered = await send_photo_to_user(path, caption=title)
    return {"created": True, "path": path, "delivered": delivered,
            "note": "Chart sent to your Telegram." if delivered else f"Saved at {path}."}

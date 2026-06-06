"""Chart rendering (matplotlib, headless).

Renders bar/line/pie charts to PNG for delivery as images or embedding in PDFs.
Uses the non-interactive Agg backend so it works on a server with no display.
matplotlib is imported lazily so the rest of the app runs even if it's absent.
"""
import os
from datetime import datetime

CHART_DIR = "./data/documents"


def render_chart(chart_type: str, labels, values, title: str = "", out_path: str = None) -> str:
    """Render a chart to a PNG file and return its path."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [str(x) for x in (labels or [])]
    values = [float(x) for x in (values or [])]
    if not labels or not values:
        raise ValueError("Chart needs non-empty labels and values.")

    if out_path is None:
        os.makedirs(CHART_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(CHART_DIR, f"chart_{stamp}.png")

    ct = (chart_type or "bar").lower()
    fig, ax = plt.subplots(figsize=(8, 4.5))
    try:
        if ct == "line":
            ax.plot(labels, values, marker="o", color="#2563eb")
            ax.grid(True, axis="y", alpha=0.3)
        elif ct == "pie":
            ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90)
            ax.axis("equal")
        else:  # bar (default)
            ax.bar(labels, values, color="#2563eb")
            ax.grid(True, axis="y", alpha=0.3)
        if title:
            ax.set_title(title)
        if ct != "pie" and len(labels) > 4:
            fig.autofmt_xdate(rotation=30)
        fig.tight_layout()
        fig.savefig(out_path, dpi=120)
    finally:
        plt.close(fig)
    return out_path

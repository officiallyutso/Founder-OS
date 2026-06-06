"""Document generation tools.

The agent kept trying to *self-author* a PDF tool, which can never work: the
self-authored-tool sandbox blocks file writing and non-whitelisted imports. So
PDF/document generation is provided here as a proper built-in tool.

`generate_pdf` writes a real PDF (via fpdf2 if installed, falling back to a .txt
file otherwise) into data/documents/ and — when the bot is running — delivers the
file straight to the founder on Telegram.
"""
import os
import re
from datetime import datetime

from agent.registry import register

DOCS_DIR = "./data/documents"


def _safe_filename(name: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9._-]+", "_", (name or "document").strip())[:60].strip("_")
    base = base or "document"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{base}_{stamp}"


def _latin1(text: str) -> str:
    """fpdf2 core fonts are latin-1 only; replace anything outside it."""
    return (text or "").encode("latin-1", "replace").decode("latin-1")


def _write_pdf(safe: str, title: str, content: str):
    """Return (path, format). Try a real PDF; fall back to .txt if fpdf2 is absent."""
    os.makedirs(DOCS_DIR, exist_ok=True)
    try:
        from fpdf import FPDF

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        # pdf.write() wraps at the right margin and honors '\n'; it avoids the
        # multi_cell(w=0) "not enough horizontal space" edge case.
        pdf.set_font("Helvetica", "B", 16)
        pdf.write(9, _latin1(title))
        pdf.ln(13)
        pdf.set_font("Helvetica", size=12)
        pdf.write(7, _latin1(content or ""))
        path = os.path.join(DOCS_DIR, safe + ".pdf")
        pdf.output(path)
        return path, "pdf"
    except Exception:
        # fpdf2 not installed (or failed) → still produce a usable text document.
        path = os.path.join(DOCS_DIR, safe + ".txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"{title}\n{'=' * len(title)}\n\n{content or ''}")
        return path, "txt"


async def _deliver(path: str, caption: str) -> bool:
    """Send the generated file to the founder on Telegram if the bot is live."""
    try:
        from scheduler.jobs import send_document_to_user
        return await send_document_to_user(path, caption=caption)
    except Exception:
        return False


@register(
    name="generate_pdf",
    description="Generate a PDF document from text content (a report, brief, one-pager, "
                "memo, agenda, etc.) and deliver it to the founder on Telegram. Provide a "
                "title and the full body content. Falls back to a .txt file if PDF support "
                "isn't installed.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Document title / heading."},
            "content": {"type": "string", "description": "The full body text (plain text; newlines become paragraphs)."},
            "filename": {"type": "string", "description": "Optional base filename (no extension)."},
        },
        "required": ["title", "content"],
    },
    category="tasks",
)
async def generate_pdf(title: str, content: str, filename: str = None):
    safe = _safe_filename(filename or title)
    path, fmt = _write_pdf(safe, title, content)
    delivered = await _deliver(path, caption=title[:1000])
    note = "Sent to your Telegram." if delivered else f"Saved locally at {path}."
    if fmt == "txt":
        note += " (Install fpdf2 for real PDFs: pip install fpdf2)"
    return {"created": True, "format": fmt, "path": path, "delivered": delivered, "note": note}


@register(
    name="create_document",
    description="Create a plain-text or Markdown document file from content and deliver it "
                "to the founder on Telegram. Use for notes, specs, or drafts where a .pdf "
                "isn't required. Do NOT use this for voice/audio requests — use send_voice_note instead.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string"},
            "extension": {"type": "string", "enum": ["txt", "md"], "description": "Defaults to md."},
            "filename": {"type": "string"},
        },
        "required": ["title", "content"],
    },
    category="tasks",
)
async def create_document(title: str, content: str, extension: str = "md", filename: str = None):
    os.makedirs(DOCS_DIR, exist_ok=True)
    ext = extension if extension in ("txt", "md") else "md"
    safe = _safe_filename(filename or title)
    path = os.path.join(DOCS_DIR, f"{safe}.{ext}")
    heading = f"# {title}\n\n" if ext == "md" else f"{title}\n{'=' * len(title)}\n\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(heading + (content or ""))
    delivered = await _deliver(path, caption=title[:1000])
    return {"created": True, "format": ext, "path": path, "delivered": delivered,
            "note": "Sent to your Telegram." if delivered else f"Saved locally at {path}."}

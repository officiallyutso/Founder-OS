"""Document text extraction (PDF / DOCX / plain text), optional deps, lazy-loaded.

Setup (optional):  pip install pypdf python-docx
"""
import io
import logging

logger = logging.getLogger(__name__)


def extract_text(raw: bytes, mime: str = "", filename: str = "", max_chars: int = 8000) -> str:
    name = (filename or "").lower()
    try:
        if mime == "application/pdf" or name.endswith(".pdf"):
            return _pdf(raw, max_chars)
        if name.endswith(".docx") or "wordprocessingml" in mime:
            return _docx(raw, max_chars)
        # Fallback: try utf-8 text.
        return raw.decode("utf-8", errors="replace")[:max_chars]
    except Exception as e:
        logger.error(f"[documents] extract failed: {e}")
        return ""


def _pdf(raw: bytes, max_chars: int) -> str:
    try:
        from pypdf import PdfReader
    except Exception:
        return "(install pypdf to read PDFs: pip install pypdf)"
    reader = PdfReader(io.BytesIO(raw))
    out = []
    for page in reader.pages:
        out.append(page.extract_text() or "")
        if sum(len(x) for x in out) > max_chars:
            break
    return " ".join(" ".join(out).split())[:max_chars]


def _docx(raw: bytes, max_chars: int) -> str:
    try:
        import docx
    except Exception:
        return "(install python-docx to read .docx: pip install python-docx)"
    document = docx.Document(io.BytesIO(raw))
    return "\n".join(p.text for p in document.paragraphs)[:max_chars]

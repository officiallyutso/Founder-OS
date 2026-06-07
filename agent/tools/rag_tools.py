"""Document RAG: ingest the founder's own files and answer from them.

Point the agent at a file or folder (pitch deck, contracts, notes, specs) and it
chunks the text into the `documents` vector collection. `ask_documents` then does
semantic retrieval over just those files, so answers are grounded in your own
material rather than only chat history. Because `documents` is part of the shared
collection set, ingested files also surface through normal memory search.
"""
import os

from agent.registry import register
from memory import vector_store
from integrations import documents as doc_extract

SUPPORTED_EXT = {".pdf", ".docx", ".txt", ".md", ".markdown", ".rst", ".csv", ".json"}


def _chunk(text: str, size: int = 1000, overlap: int = 150) -> list:
    text = " ".join((text or "").split())
    if not text:
        return []
    chunks, i, n = [], 0, len(text)
    step = max(size - overlap, 1)
    while i < n:
        chunks.append(text[i:i + size])
        i += step
    return chunks


def _ingest_one(path: str) -> dict:
    if not os.path.isfile(path):
        return {"error": f"No file at {path}"}
    fname = os.path.basename(path)
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        return {"error": f"Could not read {fname}: {e}"}
    text = doc_extract.extract_text(raw, filename=fname, max_chars=300_000)
    chunks = _chunk(text)
    if not chunks:
        return {"error": f"No extractable text in {fname}"}
    col = vector_store.get_collection("documents")
    # Replace any prior ingest of the same file so re-ingesting stays idempotent.
    try:
        col.delete(where={"source": fname})
    except Exception:
        pass
    for i, ch in enumerate(chunks):
        vector_store.add("documents", ch, metadata={
            "source": fname, "path": os.path.abspath(path), "chunk": i,
        })
    return {"ingested": fname, "chunks": len(chunks), "chars": len(text)}


@register(
    name="ingest_file",
    description="Ingest a single local document (PDF/DOCX/TXT/MD/CSV/JSON) into the agent's "
                "knowledge base so it can answer questions grounded in that file. Returns chunk count.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Absolute or relative path to the file."}},
        "required": ["path"],
    },
    category="research",
)
def ingest_file(path):
    return _ingest_one(path)


@register(
    name="ingest_folder",
    description="Ingest all supported documents in a folder (PDF/DOCX/TXT/MD/CSV/JSON) into the "
                "knowledge base. Use to load a whole directory of company material at once.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the folder."},
            "recursive": {"type": "boolean", "description": "Recurse into subfolders (default true)."},
        },
        "required": ["path"],
    },
    category="research",
)
def ingest_folder(path, recursive=True):
    if not os.path.isdir(path):
        return {"error": f"No folder at {path}"}
    walker = os.walk(path) if recursive else [(path, [], os.listdir(path))]
    ingested, total, errors = [], 0, []
    for root, _dirs, files in walker:
        for fn in files:
            if os.path.splitext(fn)[1].lower() not in SUPPORTED_EXT:
                continue
            r = _ingest_one(os.path.join(root, fn))
            if r.get("chunks"):
                ingested.append(r["ingested"])
                total += r["chunks"]
            elif r.get("error"):
                errors.append(r["error"])
    return {
        "files_ingested": len(ingested),
        "total_chunks": total,
        "files": ingested[:50],
        "errors": errors[:10],
    }


@register(
    name="ask_documents",
    description="Answer a question grounded in the founder's ingested documents using "
                "Corrective RAG: it retrieves passages, grades their relevance, rewrites and "
                "re-retrieves if they're weak, and only falls back to the web if nothing fits. "
                "Returns a synthesized answer with a confidence level and cited source files "
                "(and says so honestly if the docs don't contain the answer). Use after "
                "ingest_file/ingest_folder.",
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "k": {"type": "integer", "description": "How many passages to retrieve (default 6)."},
            "allow_web": {"type": "boolean",
                          "description": "Fall back to web search if the docs don't answer it (default true)."},
        },
        "required": ["question"],
    },
    category="research",
)
async def ask_documents(question, k=6, allow_web=True):
    from agent import self_rag
    try:
        k = max(1, min(int(k or 6), 12))
    except (TypeError, ValueError):
        k = 6
    return await self_rag.answer(question, k=k, allow_web=bool(allow_web))


@register(
    name="list_ingested_documents",
    description="List which documents have been ingested into the knowledge base and how many chunks each has.",
    parameters={"type": "object", "properties": {}},
    category="research",
)
def list_ingested_documents():
    col = vector_store.get_collection("documents")
    try:
        got = col.get(include=["metadatas"])
    except Exception:
        return {"documents": [], "count": 0}
    counts = {}
    for m in (got.get("metadatas") or []):
        src = (m or {}).get("source", "?")
        counts[src] = counts.get(src, 0) + 1
    items = [{"source": s, "chunks": n} for s, n in sorted(counts.items())]
    return {"documents": items, "count": len(items)}

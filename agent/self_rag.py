"""Self-RAG / Corrective RAG over the founder's ingested documents.

Plain RAG retrieves top-k chunks and hopes they're relevant. This pipeline is
self-correcting:

  1. Retrieve (hybrid dense+sparse) from the `documents` collection.
  2. GRADE the passages with the LLM: which are actually relevant, and are they
     sufficient to answer confidently? (Self-RAG reflection.)
  3. If insufficient, CORRECT: rewrite the query, re-retrieve, re-grade. (CRAG.)
  4. If still nothing relevant, fall back to web search (clearly labelled).
  5. SYNTHESIZE a grounded answer that cites source filenames, with an explicit
     confidence level — and says "not in your documents" instead of hallucinating.

All LLM calls go through the router (budget-checked, cached). Helper functions are
module-level so they can be monkeypatched in tests without hitting the network.
"""
import json
import logging

from llm.router import complete
from memory.retrieval import hybrid_search

logger = logging.getLogger(__name__)


def _clean_json(raw: str) -> str:
    return (raw or "").strip().replace("```json", "").replace("```", "").strip()


def _retrieve(question: str, k: int) -> list:
    hits = hybrid_search(question, collections=["documents"], k=k)
    return [{"source": (h.get("metadata") or {}).get("source", "?"),
             "text": h.get("text", "")} for h in hits if h.get("text")]


async def _grade(question: str, chunks: list) -> tuple:
    """Return (relevant_indices, sufficient). One LLM call for the whole set."""
    listing = "\n\n".join(
        f"[{i}] (source: {c['source']})\n{c['text'][:500]}" for i, c in enumerate(chunks))
    messages = [
        {"role": "system", "content":
            "You grade retrieved passages for a question. Decide which passages are "
            "relevant and whether, together, they are SUFFICIENT to answer confidently. "
            "Respond ONLY with JSON."},
        {"role": "user", "content":
            f"QUESTION:\n{question}\n\nPASSAGES:\n{listing}\n\n"
            'Return JSON: {"relevant": [indices], "sufficient": true/false}'},
    ]
    raw = await complete(messages, task_type="analysis", max_tokens=200)
    data = json.loads(_clean_json(raw))
    idxs = [i for i in (data.get("relevant") or [])
            if isinstance(i, int) and 0 <= i < len(chunks)]
    return idxs, bool(data.get("sufficient", False))


async def _rewrite(question: str) -> str:
    messages = [
        {"role": "system", "content":
            "Rewrite the question into a stronger document-search query: add keywords, "
            "synonyms, and expansions. Return ONLY the rewritten query on one line."},
        {"role": "user", "content": question},
    ]
    raw = await complete(messages, task_type="general", max_tokens=60)
    line = (raw or "").strip().splitlines()
    return line[0][:300] if line else question


async def _synthesize(question: str, chunks: list) -> str:
    ctx = "\n\n".join(f"(source: {c['source']})\n{c['text']}" for c in chunks)
    messages = [
        {"role": "system", "content":
            "Answer the question using ONLY the provided sources. Cite source filenames "
            "inline like (source: file.pdf). If the sources do not contain the answer, "
            "say so plainly instead of guessing. Be concise."},
        {"role": "user", "content": f"QUESTION:\n{question}\n\nSOURCES:\n{ctx[:6000]}"},
    ]
    return (await complete(messages, task_type="analysis", max_tokens=600)).strip()


def _dedup_merge(primary: list, extra: list) -> list:
    seen = {c["text"][:120] for c in primary}
    return primary + [c for c in extra if c["text"][:120] not in seen]


async def answer(question: str, k: int = 6, allow_web: bool = True) -> dict:
    """Corrective-RAG answer grounded in ingested documents (web fallback optional)."""
    chunks = _retrieve(question, k)
    used_correction = False

    if chunks:
        idxs, sufficient = await _grade(question, chunks)
        relevant = [chunks[i] for i in idxs]
    else:
        relevant, sufficient = [], False

    # CORRECT: rewrite + re-retrieve when the first pass is weak.
    if not sufficient:
        used_correction = True
        try:
            rq = await _rewrite(question)
            merged = _dedup_merge(relevant, _retrieve(rq, k))
            if merged:
                idxs2, sufficient2 = await _grade(question, merged)
                relevant = [merged[i] for i in idxs2] or relevant
                sufficient = sufficient or sufficient2
        except Exception as e:
            logger.debug(f"[self_rag] correction skipped: {e}")

    if relevant:
        confidence = "high" if (sufficient and len(relevant) >= 2) else "medium"
        ans = await _synthesize(question, relevant[:k])
        return {"answer": ans, "confidence": confidence,
                "sources": sorted({c["source"] for c in relevant}),
                "used_correction": used_correction, "web_fallback": False}

    # FALL BACK: nothing relevant in the founder's docs.
    if allow_web:
        try:
            from tools.web_search import search as web_search
            web = web_search(question, num_results=4) or []
        except Exception:
            web = []
        if web:
            lines = "\n".join(f"- {w.get('title', '')}: {w.get('url', '')}" for w in web)
            return {"answer": "Not in your documents. From the web:\n" + lines,
                    "confidence": "low", "sources": [],
                    "used_correction": used_correction, "web_fallback": True, "web": web}

    return {"answer": "I couldn't find this in your ingested documents.",
            "confidence": "low", "sources": [],
            "used_correction": used_correction, "web_fallback": False}

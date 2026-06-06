"""Semantic cache for plain LLM completions.

Repeated or near-identical prompts (planning the same kind of goal, re-analyzing
similar inputs) don't need a fresh paid call. We embed the request and look for a
near-duplicate in a dedicated Chroma collection; a close enough hit returns the
cached answer. Only applied to side-effect-free task types, with a conservative
similarity threshold so we never serve a stale answer to a genuinely new question.
"""
import logging

from config import config

logger = logging.getLogger(__name__)

_COLLECTION = "llm_cache"
# Task types that are safe and worthwhile to cache (deterministic-ish, reusable).
CACHEABLE = {"analysis", "general", "research"}


def _query_text(messages: list, task_type: str) -> str:
    """Build a cache key from the user/system content of the request."""
    parts = [task_type]
    for m in messages:
        if m.get("role") in ("user", "system"):
            parts.append(str(m.get("content", ""))[:1500])
    return "\n".join(parts)


def get(messages: list, task_type: str):
    if not config.semantic_cache or task_type not in CACHEABLE:
        return None
    try:
        from memory.vector_store import search
        q = _query_text(messages, task_type)
        hits = search(_COLLECTION, q, n_results=1)
        if not hits:
            return None
        hit = hits[0]
        dist = hit.get("distance")
        if dist is not None and dist <= config.cache_distance_threshold:
            meta = hit.get("metadata") or {}
            if meta.get("task_type") == task_type and meta.get("answer"):
                logger.info(f"[cache] hit (dist={dist:.4f}) task={task_type}")
                return meta["answer"]
    except Exception as e:
        logger.debug(f"[cache] get skipped: {e}")
    return None


def put(messages: list, task_type: str, answer: str):
    if not config.semantic_cache or task_type not in CACHEABLE or not answer:
        return
    try:
        from memory.vector_store import add
        q = _query_text(messages, task_type)
        add(_COLLECTION, q, metadata={"task_type": task_type, "answer": answer[:4000]})
    except Exception as e:
        logger.debug(f"[cache] put skipped: {e}")

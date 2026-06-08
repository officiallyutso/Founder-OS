"""Hybrid retrieval: dense (vector) + sparse (BM25) fused with Reciprocal Rank
Fusion, plus optional cross-encoder reranking and Generative-Agents-style
episodic scoring (relevance + recency + importance).

Design choices for a local/free single-user setup:
  - Dense recall uses the existing Chroma store.
  - Sparse recall uses rank_bm25 (tiny, pure-Python). If it's not installed we
    degrade gracefully to dense-only.
  - Fusion is RRF (no tuning, no extra model needed).
  - A cross-encoder reranker is used ONLY if sentence-transformers is present;
    otherwise RRF order stands. This avoids forcing a heavy torch dependency.
"""
import logging
import time

from memory.vector_store import get_collection, search, COLLECTIONS

logger = logging.getLogger(__name__)

_RRF_K = 60
_bm25_warned = False
_cross_encoder = None
_cross_encoder_tried = False


def _bm25_rank(collection_name: str, query: str, k: int) -> list:
    """Return up to k documents from a collection ranked by BM25."""
    global _bm25_warned
    try:
        from rank_bm25 import BM25Okapi
    except Exception:
        if not _bm25_warned:
            logger.info("[retrieval] rank_bm25 not installed; using dense-only recall.")
            _bm25_warned = True
        return []
    try:
        col = get_collection(collection_name)
        data = col.get(include=["documents", "metadatas"])
        docs = data.get("documents") or []
        if not docs:
            return []
        corpus = [d.lower().split() for d in docs]
        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(query.lower().split())
        ranked = sorted(range(len(docs)), key=lambda i: scores[i], reverse=True)[:k]
        metas = data.get("metadatas") or [{}] * len(docs)
        return [{"text": docs[i], "metadata": metas[i] if i < len(metas) else {},
                 "collection": collection_name} for i in ranked if scores[i] > 0]
    except Exception as e:
        logger.debug(f"[retrieval] bm25 failed on {collection_name}: {e}")
        return []


def _maybe_rerank(query: str, items: list, k: int) -> list:
    """Cross-encoder rerank if available; otherwise return items unchanged."""
    global _cross_encoder, _cross_encoder_tried
    if not items:
        return items
    if not _cross_encoder_tried:
        _cross_encoder_tried = True
        try:
            from sentence_transformers import CrossEncoder
            _cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        except Exception:
            _cross_encoder = None
    if _cross_encoder is None:
        return items[:k]
    try:
        pairs = [(query, it["text"]) for it in items]
        scores = _cross_encoder.predict(pairs)
        for it, s in zip(items, scores):
            it["rerank_score"] = float(s)
        return sorted(items, key=lambda x: x.get("rerank_score", 0), reverse=True)[:k]
    except Exception:
        return items[:k]


def hybrid_search(query: str, collections: list = None, k: int = 8) -> list:
    """Dense + sparse retrieval fused with RRF, then optional rerank."""
    collections = collections or COLLECTIONS
    fused = {}

    for coll in collections:
        dense = search(coll, query, n_results=k)
        for rank, item in enumerate(dense):
            key = (coll, item["text"][:120])
            fused.setdefault(key, {"text": item["text"], "collection": coll,
                                   "metadata": item.get("metadata", {}), "score": 0.0})
            fused[key]["score"] += 1.0 / (_RRF_K + rank)

        sparse = _bm25_rank(coll, query, k)
        for rank, item in enumerate(sparse):
            key = (coll, item["text"][:120])
            fused.setdefault(key, {"text": item["text"], "collection": coll,
                                   "metadata": item.get("metadata", {}), "score": 0.0})
            fused[key]["score"] += 1.0 / (_RRF_K + rank)

    ranked = sorted(fused.values(), key=lambda x: x["score"], reverse=True)[: k * 2]
    return _maybe_rerank(query, ranked, k)


def fused_recall(query: str, k: int = 8, text_collections: list = None,
                 max_entities: int = 5) -> dict:
    """Cross-module recall: hybrid text retrieval + knowledge-graph relationships.

    This is *context* fusion, not score fusion across modalities (mixing text
    chunks and graph edges into one ranked list is unreliable). Instead:
      1. Hybrid (dense+sparse, RRF) text recall — already ranked.
      2. Detect known graph entities in the query AND the top text snippets
         (the multi-hop bridge: text surfaces a name, the graph expands it).
      3. Attach each entity's relationships.
    The graph half is wrapped so any failure degrades to text-only recall.
    """
    text_hits = hybrid_search(query, collections=text_collections, k=k)

    entities, relations = [], []
    try:
        from memory import graph
        probe = query + " " + " ".join(
            (h.get("text") or "")[:200] for h in text_hits[:5])
        found = graph.find_entities(probe, limit=max_entities)
        entities = [e["name"] for e in found]
        seen = set()
        for e in found:
            for rel in graph.neighbors(e["name"], limit=10):
                key = (rel.get("src"), rel.get("rel"), rel.get("dst"))
                if key not in seen:
                    seen.add(key)
                    relations.append(rel)
    except Exception as e:
        logger.debug(f"[retrieval] fused_recall graph step skipped: {e}")

    return {
        "query": query,
        "entities": entities,
        "text": [{"collection": h.get("collection"), "text": h.get("text", "")}
                 for h in text_hits],
        "relations": relations,
    }


def episodic_recall(query: str, k: int = 6) -> list:
    """Recall conversation/episodic memory weighted by relevance + recency.

    Approximates the Generative Agents retrieval function: combine semantic
    relevance (from hybrid search ordering) with recency (timestamp decay) and
    an optional importance score stored in metadata.
    """
    items = hybrid_search(query, collections=["conversations"], k=k * 2)
    now = time.time()
    for i, it in enumerate(items):
        relevance = 1.0 / (1 + i)  # rank-based proxy
        ts = (it.get("metadata") or {}).get("timestamp", now)
        try:
            age_days = max(0.0, (now - float(ts)) / 86400.0)
        except Exception:
            age_days = 0.0
        recency = 0.99 ** age_days
        importance = float((it.get("metadata") or {}).get("importance", 1.0))
        it["recall_score"] = relevance + recency + 0.3 * importance
    return sorted(items, key=lambda x: x["recall_score"], reverse=True)[:k]

"""Vector store with a pluggable backend.

Default backend is **Chroma** (local, on-disk under data/chroma) — zero setup and
perfect for a single box. Set ``VECTOR_BACKEND=qdrant`` (+ ``QDRANT_URL`` /
``QDRANT_API_KEY``) to use a managed/remote **Qdrant** cluster instead, e.g. the
Qdrant Cloud free tier.

Both backends are exposed through the same tiny Chroma-style collection API
(``count`` / ``add`` / ``query`` / ``get`` / ``delete``) so the rest of the app
(retrieval, BM25, document RAG, caching) is backend-agnostic. Embeddings use the
same local model regardless of backend, so the two stores are interchangeable.
"""
import logging
import os
import time
import uuid

from config import config

# ChromaDB can emit noisy PostHog telemetry on some dependency combos. Disable it
# before chromadb is imported anywhere so it never starts.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY_IMPL", "chromadb.telemetry.product.null.NullTelemetry")

logger = logging.getLogger(__name__)

COLLECTIONS = ["conversations", "research", "notes", "outreach", "documents"]

_BACKEND = (getattr(config, "vector_backend", "chroma") or "chroma").strip().lower()
if _BACKEND == "qdrant" and not getattr(config, "qdrant_url", ""):
    logger.warning("[vector_store] VECTOR_BACKEND=qdrant but QDRANT_URL is empty; "
                   "falling back to local Chroma.")
    _BACKEND = "chroma"

_chroma_client = None
_qdrant = None              # tuple: (client, embedder, dim)
_qdrant_collections = {}    # name -> _QdrantCollection adapter


# ── Chroma backend ────────────────────────────────────────────────────────────

def _get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        import chromadb
        from chromadb.config import Settings
        os.makedirs("./data/chroma", exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path="./data/chroma",
            settings=Settings(anonymized_telemetry=False),
        )
    return _chroma_client


# ── Qdrant backend ────────────────────────────────────────────────────────────

def _get_qdrant():
    """Lazily build the Qdrant client + shared embedder. Embeddings reuse Chroma's
    bundled local model so vectors match the Chroma backend exactly."""
    global _qdrant
    if _qdrant is None:
        from qdrant_client import QdrantClient
        from chromadb.utils import embedding_functions
        client = QdrantClient(url=config.qdrant_url, api_key=config.qdrant_api_key or None)
        embedder = embedding_functions.DefaultEmbeddingFunction()
        dim = len(embedder(["dimension probe"])[0])
        _qdrant = (client, embedder, dim)
    return _qdrant


def _where_to_filter(where: dict):
    if not where:
        return None
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    must = [FieldCondition(key=k, match=MatchValue(value=v)) for k, v in where.items()]
    return Filter(must=must)


class _QdrantCollection:
    """Adapter exposing the subset of the Chroma collection API the app uses."""

    def __init__(self, client, name, embedder, dim):
        self.client = client
        self.name = name
        self.embedder = embedder
        from qdrant_client.models import Distance, VectorParams
        names = {c.name for c in client.get_collections().collections}
        if name not in names:
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )

    def count(self) -> int:
        return self.client.count(self.name, exact=True).count

    def add(self, documents, metadatas=None, ids=None):
        from qdrant_client.models import PointStruct
        metadatas = metadatas or [{} for _ in documents]
        ids = ids or [str(uuid.uuid4()) for _ in documents]
        vectors = self.embedder(list(documents))
        points = []
        for doc, meta, _id, vec in zip(documents, metadatas, ids, vectors):
            payload = dict(meta or {})
            payload["document"] = doc
            points.append(PointStruct(id=_id, vector=list(vec), payload=payload))
        self.client.upsert(collection_name=self.name, points=points)

    def query(self, query_texts, n_results: int = 5) -> dict:
        qvec = list(self.embedder(list(query_texts))[0])
        resp = self.client.query_points(collection_name=self.name, query=qvec,
                                        limit=n_results, with_payload=True)
        docs, metas, ids, dists = [], [], [], []
        for h in resp.points:
            payload = dict(h.payload or {})
            docs.append(payload.pop("document", ""))
            metas.append(payload)
            ids.append(str(h.id))
            # Chroma reports a distance (lower = closer); Qdrant Cosine reports a
            # similarity score (higher = closer). Convert so callers stay uniform.
            dists.append(1.0 - float(h.score))
        return {"documents": [docs], "metadatas": [metas], "ids": [ids], "distances": [dists]}

    def get(self, ids=None, where=None, include=None, limit=None) -> dict:
        include = include or []
        if ids:
            recs = self.client.retrieve(self.name, ids=ids, with_payload=True)
        else:
            recs, _ = self.client.scroll(self.name, scroll_filter=_where_to_filter(where),
                                         with_payload=True, limit=limit or 10_000)
        out_ids, out_docs, out_metas = [], [], []
        for r in recs:
            payload = dict(r.payload or {})
            out_ids.append(str(r.id))
            out_docs.append(payload.pop("document", ""))
            out_metas.append(payload)
        res = {"ids": out_ids}
        if "documents" in include:
            res["documents"] = out_docs
        if "metadatas" in include:
            res["metadatas"] = out_metas
        return res

    def delete(self, ids=None, where=None):
        if ids:
            self.client.delete(self.name, points_selector=ids)
        elif where:
            from qdrant_client.models import FilterSelector
            self.client.delete(self.name,
                               points_selector=FilterSelector(filter=_where_to_filter(where)))


# ── Public API (backend-agnostic) ─────────────────────────────────────────────

def get_collection(name: str):
    if _BACKEND == "qdrant":
        if name not in _qdrant_collections:
            client, embedder, dim = _get_qdrant()
            _qdrant_collections[name] = _QdrantCollection(client, name, embedder, dim)
        return _qdrant_collections[name]
    return _get_chroma_client().get_or_create_collection(name)


def add(collection_name: str, text: str, metadata: dict = None, doc_id: str = None):
    col = get_collection(collection_name)
    doc_id = doc_id or str(uuid.uuid4())
    meta = {"timestamp": time.time(), "source": collection_name}
    if metadata:
        meta.update(metadata)
    col.add(documents=[text], metadatas=[meta], ids=[doc_id])
    return doc_id


def search(collection_name: str, query: str, n_results: int = 5) -> list:
    col = get_collection(collection_name)
    count = col.count()
    if count == 0:
        return []
    results = col.query(query_texts=[query], n_results=min(n_results, count))
    items = []
    for i, doc in enumerate(results["documents"][0]):
        items.append({
            "text": doc,
            "metadata": results["metadatas"][0][i],
            "id": results["ids"][0][i],
            "distance": results["distances"][0][i] if results.get("distances") else None,
            "collection": collection_name,
        })
    return items


def search_all(query: str, n_results: int = 3) -> list:
    all_results = []
    for col_name in COLLECTIONS:
        results = search(col_name, query, n_results=n_results)
        all_results.extend(results)
    # Sort by distance (lower = more relevant)
    all_results.sort(key=lambda x: x.get("distance") or 999)
    return all_results[:n_results * 2]


def delete(collection_name: str, doc_id: str):
    col = get_collection(collection_name)
    col.delete(ids=[doc_id])


def get_recent(collection_name: str, limit: int = 10) -> list:
    col = get_collection(collection_name)
    count = col.count()
    if count == 0:
        return []
    results = col.get(limit=min(limit, count), include=["documents", "metadatas"])
    items = []
    for i, doc in enumerate(results["documents"]):
        items.append({
            "text": doc,
            "metadata": results["metadatas"][i],
            "id": results["ids"][i],
        })
    # Sort by timestamp descending
    items.sort(key=lambda x: x["metadata"].get("timestamp", 0), reverse=True)
    return items

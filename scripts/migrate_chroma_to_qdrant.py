"""Copy existing local Chroma vectors into a Qdrant cluster.

Use this once when switching ``VECTOR_BACKEND`` from ``chroma`` to ``qdrant`` so you
don't lose already-embedded memory/documents. It copies the **stored embeddings**
directly (no re-embedding), preserving vectors exactly.

Prerequisites:
  - Your local Chroma store at ./data/chroma (the default location).
  - A Qdrant cluster: set QDRANT_URL (+ QDRANT_API_KEY) in the environment / .env.

Run:
    python scripts/migrate_chroma_to_qdrant.py            # migrate all collections
    python scripts/migrate_chroma_to_qdrant.py --recreate # drop & recreate first
    python scripts/migrate_chroma_to_qdrant.py --collections notes documents

Then set VECTOR_BACKEND=qdrant in .env and restart the app.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

from config import config  # noqa: E402
from memory.vector_store import COLLECTIONS  # noqa: E402

BATCH = 256
CHROMA_PATH = "./data/chroma"


def _chroma_client():
    import chromadb
    from chromadb.config import Settings
    if not os.path.isdir(CHROMA_PATH):
        sys.exit(f"No Chroma store found at {CHROMA_PATH} — nothing to migrate.")
    return chromadb.PersistentClient(path=CHROMA_PATH,
                                     settings=Settings(anonymized_telemetry=False))


def _qdrant_client():
    if not config.qdrant_url:
        sys.exit("QDRANT_URL is not set. Put it in your environment / .env first.")
    from qdrant_client import QdrantClient
    return QdrantClient(url=config.qdrant_url, api_key=config.qdrant_api_key or None)


def _ensure_collection(qc, name, dim, recreate):
    from qdrant_client.models import Distance, VectorParams
    existing = {c.name for c in qc.get_collections().collections}
    if name in existing and recreate:
        qc.delete_collection(name)
        existing.discard(name)
    if name not in existing:
        qc.create_collection(collection_name=name,
                             vectors_config=VectorParams(size=dim, distance=Distance.COSINE))


def _migrate_collection(cc, qc, name, recreate):
    from qdrant_client.models import PointStruct
    try:
        col = cc.get_collection(name)
    except Exception:
        print(f"  • {name}: not present in Chroma, skipping")
        return 0
    total = col.count()
    if total == 0:
        print(f"  • {name}: empty, skipping")
        return 0

    moved = 0
    offset = 0
    ensured = False
    while offset < total:
        page = col.get(include=["documents", "metadatas", "embeddings"],
                       limit=BATCH, offset=offset)
        ids = page.get("ids") or []
        if not ids:
            break
        docs = page.get("documents") or [""] * len(ids)
        metas = page.get("metadatas") or [{}] * len(ids)
        embs = page.get("embeddings") or []
        if not embs:
            sys.exit(f"  ! {name}: Chroma returned no embeddings — cannot migrate.")

        if not ensured:
            _ensure_collection(qc, name, dim=len(embs[0]), recreate=recreate)
            ensured = True

        points = []
        for _id, doc, meta, vec in zip(ids, docs, metas, embs):
            payload = dict(meta or {})
            payload["document"] = doc
            points.append(PointStruct(id=_id, vector=list(vec), payload=payload))
        qc.upsert(collection_name=name, points=points)

        moved += len(points)
        offset += len(ids)
        print(f"  • {name}: {moved}/{total}")
    return moved


def main():
    parser = argparse.ArgumentParser(description="Migrate Chroma vectors to Qdrant.")
    parser.add_argument("--collections", nargs="*", default=COLLECTIONS,
                        help="Collection names to migrate (default: all known).")
    parser.add_argument("--recreate", action="store_true",
                        help="Drop each target Qdrant collection before copying.")
    args = parser.parse_args()

    cc = _chroma_client()
    qc = _qdrant_client()

    print(f"Migrating {len(args.collections)} collection(s) to {config.qdrant_url}")
    grand = 0
    for name in args.collections:
        grand += _migrate_collection(cc, qc, name, args.recreate)
    print(f"\nDone. Migrated {grand} vectors. "
          f"Now set VECTOR_BACKEND=qdrant in .env and restart.")


if __name__ == "__main__":
    main()

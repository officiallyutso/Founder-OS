"""Exercise the Qdrant adapter end-to-end via Qdrant's in-process memory mode.

Uses a tiny deterministic fake embedder (4-dim) so no model download is needed.
Verifies the adapter speaks the Chroma-style API the rest of the app relies on.
"""
import pytest

qdrant_client = pytest.importorskip("qdrant_client")

from memory import vector_store


def _embedder(texts):
    # Deterministic, non-zero vectors keyed on simple character features.
    return [[float(len(t)), float(t.count("a")), float(t.count("b")), 1.0] for t in texts]


@pytest.fixture
def collection():
    from qdrant_client import QdrantClient
    client = QdrantClient(location=":memory:")
    return vector_store._QdrantCollection(client, "test", _embedder, dim=4)


def test_add_and_count(collection):
    assert collection.count() == 0
    collection.add(documents=["aaaa", "bbbb"],
                   metadatas=[{"source": "x"}, {"source": "y"}],
                   ids=["11111111-1111-1111-1111-111111111111",
                        "22222222-2222-2222-2222-222222222222"])
    assert collection.count() == 2


def test_query_returns_chroma_shape(collection):
    collection.add(documents=["aaaa", "bbbb"],
                   metadatas=[{"source": "x"}, {"source": "y"}],
                   ids=["11111111-1111-1111-1111-111111111111",
                        "22222222-2222-2222-2222-222222222222"])
    res = collection.query(query_texts=["aaaa"], n_results=2)
    assert set(res) == {"documents", "metadatas", "ids", "distances"}
    assert res["documents"][0][0] == "aaaa"          # nearest is the matching doc
    assert res["metadatas"][0][0]["source"] == "x"   # payload minus 'document'
    assert all(-0.01 <= d <= 2.01 for d in res["distances"][0])


def test_get_includes_documents_and_ids(collection):
    collection.add(documents=["aaaa"], metadatas=[{"source": "x"}],
                   ids=["11111111-1111-1111-1111-111111111111"])
    got = collection.get(include=["documents", "metadatas"])
    assert got["ids"] == ["11111111-1111-1111-1111-111111111111"]
    assert got["documents"] == ["aaaa"]
    assert got["metadatas"][0]["source"] == "x"


def test_delete_by_id(collection):
    collection.add(documents=["aaaa"], metadatas=[{"source": "x"}],
                   ids=["11111111-1111-1111-1111-111111111111"])
    collection.delete(ids=["11111111-1111-1111-1111-111111111111"])
    assert collection.count() == 0


def test_delete_by_where_filter(collection):
    collection.add(documents=["aaaa", "bbbb"],
                   metadatas=[{"source": "keep"}, {"source": "drop"}],
                   ids=["11111111-1111-1111-1111-111111111111",
                        "22222222-2222-2222-2222-222222222222"])
    collection.delete(where={"source": "drop"})
    remaining = collection.get(include=["metadatas"])
    assert [m["source"] for m in remaining["metadatas"]] == ["keep"]

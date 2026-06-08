import pytest

from memory import retrieval, graph


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    """Query-aware fake: COUNT/MAX -> signature row, else -> entity rows."""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, *args):
        s = " ".join((sql or "").split()).upper()
        if "COUNT(*)" in s:
            return _FakeCursor([{"c": len(self._rows), "u": "sig"}])
        return _FakeCursor(self._rows)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _reset_entity_cache():
    graph._entity_cache = None
    graph._entity_cache_sig = None
    yield
    graph._entity_cache = None
    graph._entity_cache_sig = None


def _entities(monkeypatch, rows):
    monkeypatch.setattr(graph, "get_conn", lambda: _FakeConn(rows))


# ── find_entities ────────────────────────────────────────────────────────────

def test_find_entities_word_boundary_no_substring(monkeypatch):
    rows = [
        {"name": "Acme", "type": "company", "attrs_json": '{"industry": "tech"}'},
        {"name": "Jane Doe", "type": "person", "attrs_json": '{"role": "CEO"}'},
        {"name": "Ann", "type": "person", "attrs_json": "{}"},  # must NOT hit "announce"
    ]
    _entities(monkeypatch, rows)

    found = graph.find_entities("Met Jane Doe at Acme about announcements")
    names = {f["name"] for f in found}
    assert names == {"Acme", "Jane Doe"}


def test_find_entities_surfaces_attrs(monkeypatch):
    rows = [{"name": "Jane Doe", "type": "person", "attrs_json": '{"role": "CEO"}'}]
    _entities(monkeypatch, rows)

    found = graph.find_entities("ping Jane Doe")
    assert found[0]["attrs"] == "role=CEO"


def test_find_entities_query_match_ranks_first(monkeypatch):
    rows = [
        {"name": "Acme", "type": "company", "attrs_json": "{}"},
        {"name": "Beta", "type": "company", "attrs_json": "{}"},
    ]
    _entities(monkeypatch, rows)

    # Both appear in the text; only Beta appears in the query -> Beta ranks first.
    found = graph.find_entities("notes mention Acme and Beta", query="what about Beta?")
    assert found[0]["name"] == "Beta"


def test_find_entities_empty_text():
    assert graph.find_entities("") == []
    assert graph.find_entities("   ") == []


# ── fused_recall ─────────────────────────────────────────────────────────────

def test_fused_recall_combines_text_and_graph(monkeypatch):
    monkeypatch.setattr(retrieval, "hybrid_search",
                        lambda q, collections=None, k=8: [
                            {"collection": "documents", "text": "Acme raised a round."},
                            {"collection": "notes", "text": "call notes"},
                        ])
    monkeypatch.setattr(graph, "find_entities",
                        lambda text, limit=5, query=None: [
                            {"name": "Acme", "type": "company", "attrs": ""}])
    monkeypatch.setattr(graph, "neighbors",
                        lambda name, limit=10: [
                            {"src": "Jane", "rel": "works_at", "dst": "Acme"}])

    out = retrieval.fused_recall("what about Acme?", k=4)
    assert out["entities"] == ["Acme"]
    assert len(out["text"]) == 2
    assert out["relations"][0]["src"] == "Jane"


def test_fused_recall_dedups_relations(monkeypatch):
    monkeypatch.setattr(retrieval, "hybrid_search",
                        lambda q, collections=None, k=8: [
                            {"collection": "notes", "text": "Acme and Beta"}])
    monkeypatch.setattr(graph, "find_entities",
                        lambda text, limit=5, query=None: [
                            {"name": "Acme", "type": "company", "attrs": ""},
                            {"name": "Beta", "type": "company", "attrs": ""}])
    monkeypatch.setattr(graph, "neighbors",
                        lambda name, limit=10: [
                            {"src": "Acme", "rel": "partner_of", "dst": "Beta"}])

    out = retrieval.fused_recall("Acme Beta", k=4)
    assert len(out["relations"]) == 1


def test_fused_recall_degrades_to_text_only_on_graph_error(monkeypatch):
    monkeypatch.setattr(retrieval, "hybrid_search",
                        lambda q, collections=None, k=8: [
                            {"collection": "documents", "text": "some text"}])

    def boom(text, limit=5, query=None):
        raise RuntimeError("graph down")
    monkeypatch.setattr(graph, "find_entities", boom)

    out = retrieval.fused_recall("anything", k=4)
    assert out["entities"] == []
    assert out["relations"] == []
    assert len(out["text"]) == 1

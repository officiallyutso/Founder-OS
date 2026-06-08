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


# ── neighbors_2hop ───────────────────────────────────────────────────────────

def test_neighbors_2hop_tags_hops_and_dedups(monkeypatch):
    def fake_neighbors(name, limit=10, by_weight=False):
        if name == "Acme":
            return [{"src": "Jane", "rel": "works_at", "dst": "Acme", "weight": 2.0}]
        if name == "Jane":
            return [
                {"src": "Jane", "rel": "knows", "dst": "Bob", "weight": 1.0},
                {"src": "Jane", "rel": "works_at", "dst": "Acme", "weight": 2.0},  # dup
            ]
        return []
    monkeypatch.setattr(graph, "neighbors", fake_neighbors)

    out = graph.neighbors_2hop("Acme")
    hops = {(r["src"], r["rel"], r["dst"]): r["hop"] for r in out}
    assert hops[("Jane", "works_at", "Acme")] == 1
    assert hops[("Jane", "knows", "Bob")] == 2
    assert len(out) == 2  # duplicate works_at edge collapsed


def test_neighbors_2hop_respects_total_cap(monkeypatch):
    def fake_neighbors(name, limit=10, by_weight=False):
        return [{"src": name, "rel": "r", "dst": f"{name}-{i}", "weight": 1.0}
                for i in range(10)]
    monkeypatch.setattr(graph, "neighbors", fake_neighbors)

    out = graph.neighbors_2hop("Hub", total_cap=5)
    assert len(out) == 5


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
                        lambda name, limit=10, by_weight=False: [
                            {"src": "Jane", "rel": "works_at", "dst": "Acme", "weight": 1.0}])
    monkeypatch.setattr(retrieval, "_communities_for", lambda names, cap=2: [])

    out = retrieval.fused_recall("what about Acme?", k=4)
    assert [e["name"] for e in out["entities"]] == ["Acme"]
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
                        lambda name, limit=10, by_weight=False: [
                            {"src": "Acme", "rel": "partner_of", "dst": "Beta", "weight": 1.0}])
    monkeypatch.setattr(retrieval, "_communities_for", lambda names, cap=2: [])

    out = retrieval.fused_recall("Acme Beta", k=4)
    assert len(out["relations"]) == 1


def test_fused_recall_ranks_relations_by_query_overlap(monkeypatch):
    monkeypatch.setattr(retrieval, "hybrid_search",
                        lambda q, collections=None, k=8: [{"collection": "notes", "text": "x"}])
    monkeypatch.setattr(graph, "find_entities",
                        lambda text, limit=5, query=None: [
                            {"name": "Acme", "type": "company", "attrs": ""}])
    monkeypatch.setattr(graph, "neighbors",
                        lambda name, limit=10, by_weight=False: [
                            {"src": "Acme", "rel": "located_in", "dst": "Berlin", "weight": 1.0},
                            {"src": "Acme", "rel": "raised", "dst": "funding", "weight": 1.0},
                        ])
    monkeypatch.setattr(retrieval, "_communities_for", lambda names, cap=2: [])

    out = retrieval.fused_recall("how much funding did Acme raise?", k=4, max_relations=2)
    # The 'raised/funding' edge overlaps the query and should rank first.
    assert out["relations"][0]["rel"] == "raised"


def test_fused_recall_caps_relations(monkeypatch):
    monkeypatch.setattr(retrieval, "hybrid_search",
                        lambda q, collections=None, k=8: [{"collection": "notes", "text": "x"}])
    monkeypatch.setattr(graph, "find_entities",
                        lambda text, limit=5, query=None: [
                            {"name": "Acme", "type": "company", "attrs": ""}])
    monkeypatch.setattr(graph, "neighbors",
                        lambda name, limit=10, by_weight=False: [
                            {"src": "Acme", "rel": f"r{i}", "dst": f"d{i}", "weight": 1.0}
                            for i in range(30)])
    monkeypatch.setattr(retrieval, "_communities_for", lambda names, cap=2: [])

    out = retrieval.fused_recall("Acme", k=4, max_relations=5)
    assert len(out["relations"]) == 5


def test_fused_recall_uses_two_hop_when_requested(monkeypatch):
    monkeypatch.setattr(retrieval, "hybrid_search",
                        lambda q, collections=None, k=8: [{"collection": "notes", "text": "x"}])
    monkeypatch.setattr(graph, "find_entities",
                        lambda text, limit=5, query=None: [
                            {"name": "Acme", "type": "company", "attrs": ""}])
    called = {"hop2": False}

    def two_hop(name, **kw):
        called["hop2"] = True
        return [{"src": "Acme", "rel": "knows", "dst": "Bob", "weight": 1.0, "hop": 2}]
    monkeypatch.setattr(graph, "neighbors_2hop", two_hop)
    monkeypatch.setattr(retrieval, "_communities_for", lambda names, cap=2: [])

    out = retrieval.fused_recall("Acme network", k=4, hops=2)
    assert called["hop2"] is True
    assert out["relations"][0]["dst"] == "Bob"


def test_fused_recall_attaches_communities(monkeypatch):
    monkeypatch.setattr(retrieval, "hybrid_search",
                        lambda q, collections=None, k=8: [{"collection": "notes", "text": "x"}])
    monkeypatch.setattr(graph, "find_entities",
                        lambda text, limit=5, query=None: [
                            {"name": "Acme", "type": "company", "attrs": ""}])
    monkeypatch.setattr(graph, "neighbors", lambda name, limit=10, by_weight=False: [])
    monkeypatch.setattr(retrieval, "_communities_for",
                        lambda names, cap=2: ["fintech cluster around Acme"])

    out = retrieval.fused_recall("Acme", k=4)
    assert out["communities"] == ["fintech cluster around Acme"]


def test_communities_for_matches_members(monkeypatch):
    import memory.graphrag as graphrag
    monkeypatch.setattr(graphrag, "list_communities", lambda: [
        {"summary": "fintech cluster", "members": ["Acme", "Beta"], "size": 2},
        {"summary": "healthcare cluster", "members": ["MedCo"], "size": 1},
    ])
    out = retrieval._communities_for(["acme"])  # case-insensitive
    assert out == ["fintech cluster"]


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
    assert out["communities"] == []
    assert len(out["text"]) == 1

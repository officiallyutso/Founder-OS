from memory import retrieval, graph


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *args, **kwargs):
        return _FakeCursor(self._rows)

    def close(self):
        pass


def test_find_entities_matches_known_names(monkeypatch):
    rows = [
        {"name": "Acme", "type": "company"},
        {"name": "Jane Doe", "type": "person"},
        {"name": "AI", "type": "topic"},  # too short -> ignored
    ]
    monkeypatch.setattr(graph, "get_conn", lambda: _FakeConn(rows))

    found = graph.find_entities("Met Jane Doe at acme today about AI")
    names = {f["name"] for f in found}
    assert names == {"Acme", "Jane Doe"}


def test_find_entities_empty_text():
    assert graph.find_entities("") == []
    assert graph.find_entities("   ") == []


def test_fused_recall_combines_text_and_graph(monkeypatch):
    monkeypatch.setattr(retrieval, "hybrid_search",
                        lambda q, collections=None, k=8: [
                            {"collection": "documents", "text": "Acme raised a round."},
                            {"collection": "notes", "text": "call notes"},
                        ])
    monkeypatch.setattr(graph, "find_entities",
                        lambda text, limit=5: [{"name": "Acme", "type": "company"}])
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
                        lambda text, limit=5: [{"name": "Acme", "type": "company"},
                                               {"name": "Beta", "type": "company"}])
    # Both entities surface the same edge; it should appear once.
    monkeypatch.setattr(graph, "neighbors",
                        lambda name, limit=10: [
                            {"src": "Acme", "rel": "partner_of", "dst": "Beta"}])

    out = retrieval.fused_recall("Acme Beta", k=4)
    assert len(out["relations"]) == 1


def test_fused_recall_degrades_to_text_only_on_graph_error(monkeypatch):
    monkeypatch.setattr(retrieval, "hybrid_search",
                        lambda q, collections=None, k=8: [
                            {"collection": "documents", "text": "some text"}])

    def boom(text, limit=5):
        raise RuntimeError("graph down")
    monkeypatch.setattr(graph, "find_entities", boom)

    out = retrieval.fused_recall("anything", k=4)
    assert out["entities"] == []
    assert out["relations"] == []
    assert len(out["text"]) == 1

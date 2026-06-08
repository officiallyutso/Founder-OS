import asyncio

from agent.tools import brain_tools


def _fused_stub(query, k=8, hops=1):
    return {
        "query": query,
        "entities": [{"name": "Acme", "type": "company", "attrs": "industry=tech"}],
        "relations": [{"src": "Jane", "src_type": "person", "rel": "works_at",
                       "dst": "Acme", "dst_type": "company", "hop": 1},
                      {"src": "Acme", "src_type": "company", "rel": "knows",
                       "dst": "Bob", "dst_type": "person", "hop": 2}],
        "communities": ["fintech cluster"],
        "text": [{"collection": "notes", "text": "a" * 500}],
    }


def test_smart_recall_formats_and_budgets(monkeypatch):
    monkeypatch.setattr(brain_tools, "fused_recall", _fused_stub)

    out = asyncio.run(brain_tools.smart_recall("acme", limit=5, hops=1))

    assert out["entities"] == ["Acme (company) [industry=tech]"]
    assert out["relations"][0] == "Jane (person) --works_at--> Acme (company)"
    assert out["relations"][1].endswith("(2-hop)")
    assert out["communities"] == ["fintech cluster"]
    assert len(out["text"][0]["text"]) == 300  # snippet budgeted
    assert "summary_note" in out


def test_smart_recall_clamps_args(monkeypatch):
    seen = {}

    def stub(query, k=8, hops=1):
        seen["k"], seen["hops"] = k, hops
        return {"query": query, "entities": [], "relations": [],
                "communities": [], "text": []}
    monkeypatch.setattr(brain_tools, "fused_recall", stub)

    asyncio.run(brain_tools.smart_recall("q", limit=999, hops=9))
    assert seen["k"] == 16  # capped
    assert seen["hops"] == 2  # capped to 2

    asyncio.run(brain_tools.smart_recall("q", limit="bad", hops="bad"))
    assert seen["k"] == 8  # default on bad input
    assert seen["hops"] == 1

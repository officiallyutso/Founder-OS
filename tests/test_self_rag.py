import asyncio

from agent import self_rag


def _run(coro):
    return asyncio.run(coro)


def test_sufficient_first_pass(monkeypatch):
    monkeypatch.setattr(self_rag, "_retrieve",
                        lambda q, k: [{"source": "a.pdf", "text": "alpha"},
                                      {"source": "b.pdf", "text": "beta"}])

    async def grade(q, chunks):
        return [0, 1], True
    async def synth(q, chunks):
        return "grounded answer (source: a.pdf)"
    monkeypatch.setattr(self_rag, "_grade", grade)
    monkeypatch.setattr(self_rag, "_synthesize", synth)

    out = _run(self_rag.answer("q", k=4))
    assert out["confidence"] == "high"
    assert out["used_correction"] is False
    assert out["web_fallback"] is False
    assert set(out["sources"]) == {"a.pdf", "b.pdf"}


def test_correction_recovers(monkeypatch):
    calls = {"n": 0}

    def retrieve(q, k):
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"source": "x.pdf", "text": "irrelevant"}]
        return [{"source": "y.pdf", "text": "the good chunk"}]
    monkeypatch.setattr(self_rag, "_retrieve", retrieve)

    grades = iter([([], False), ([0], True)])

    async def grade(q, chunks):
        return next(grades)
    async def rewrite(q):
        return "better query"
    async def synth(q, chunks):
        return "answer from corrected retrieval"
    monkeypatch.setattr(self_rag, "_grade", grade)
    monkeypatch.setattr(self_rag, "_rewrite", rewrite)
    monkeypatch.setattr(self_rag, "_synthesize", synth)

    out = _run(self_rag.answer("q", k=4))
    assert out["used_correction"] is True
    assert out["web_fallback"] is False
    assert "y.pdf" in out["sources"]


def test_web_fallback_when_no_docs(monkeypatch):
    monkeypatch.setattr(self_rag, "_retrieve", lambda q, k: [])

    async def rewrite(q):
        return q
    monkeypatch.setattr(self_rag, "_rewrite", rewrite)
    import tools.web_search as ws
    monkeypatch.setattr(ws, "search",
                        lambda q, num_results=4: [{"title": "T", "url": "http://x"}])

    out = _run(self_rag.answer("q", k=4, allow_web=True))
    assert out["web_fallback"] is True
    assert out["confidence"] == "low"


def test_honest_when_nothing(monkeypatch):
    monkeypatch.setattr(self_rag, "_retrieve", lambda q, k: [])

    async def rewrite(q):
        return q
    monkeypatch.setattr(self_rag, "_rewrite", rewrite)

    out = _run(self_rag.answer("q", k=4, allow_web=False))
    assert out["web_fallback"] is False
    assert out["sources"] == []
    assert "couldn't find" in out["answer"].lower()

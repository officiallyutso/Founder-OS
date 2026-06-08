"""Brain tools — hybrid recall and the knowledge graph."""
from agent.registry import register
from memory.retrieval import hybrid_search, episodic_recall, fused_recall
from memory import graph


@register(
    name="deep_recall",
    description="Best-quality memory recall: hybrid dense+sparse search across ALL memory, "
                "reranked. Use for hard recall questions where plain search_memory misses.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["query"],
    },
    category="memory",
)
async def deep_recall(query: str, limit: int = 8):
    hits = hybrid_search(query, k=limit)
    return [{"collection": h["collection"], "text": h["text"][:400]} for h in hits]


@register(
    name="recall_episodes",
    description="Recall past conversations relevant to a topic, weighted by relevance and "
                "recency (what was recently discussed).",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
    category="memory",
)
async def recall_episodes(query: str):
    hits = episodic_recall(query, k=6)
    return [{"text": h["text"][:300]} for h in hits]


def _fmt_entity(e: dict) -> str:
    s = f"{e.get('name')} ({e.get('type', '?')})"
    if e.get("attrs"):
        s += f" [{e['attrs']}]"
    return s


def _fmt_relation(r: dict) -> str:
    tag = "" if r.get("hop", 1) == 1 else " (2-hop)"
    return (f"{r.get('src')} ({r.get('src_type', '?')}) --{r.get('rel')}--> "
            f"{r.get('dst')} ({r.get('dst_type', '?')}){tag}")


@register(
    name="smart_recall",
    description="Deep CONNECTED recall: fuses hybrid (dense+sparse) text recall across ALL "
                "memory and documents WITH knowledge-graph relationships AND network community "
                "context for the people/companies in the query or surfaced by the text. Use for "
                "questions that need BOTH what was said/written AND how entities relate — e.g. "
                "'what do I know about Acme and who do I know there?', or multi-hop network+context "
                "questions. Set hops=2 to expand relationships one step further. For pure text use "
                "deep_recall; for a single entity's relationships use graph_lookup.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "description": "How many text passages to retrieve (default 8)."},
            "hops": {"type": "integer", "description": "Graph expansion depth: 1 (default) or 2."},
        },
        "required": ["query"],
    },
    category="memory",
)
async def smart_recall(query: str, limit: int = 8, hops: int = 1):
    try:
        limit = max(1, min(int(limit or 8), 16))
    except (TypeError, ValueError):
        limit = 8
    try:
        hops = 2 if int(hops) >= 2 else 1
    except (TypeError, ValueError):
        hops = 1

    res = fused_recall(query, k=limit, hops=hops)
    # Budget the payload: the loop truncates tool results at ~6500 chars, so cap
    # snippet length and count to keep the structured context intact.
    text_out = [{"collection": t["collection"], "text": (t["text"] or "")[:300]}
                for t in res["text"][:8]]
    return {
        "entities": [_fmt_entity(e) for e in res["entities"]],
        "relations": [_fmt_relation(r) for r in res["relations"]],
        "communities": res.get("communities", []),
        "text": text_out,
        "summary_note": (f"Fused {len(res['text'])} passages, {len(res['relations'])} relations, "
                         f"{len(res['entities'])} entities, "
                         f"{len(res.get('communities', []))} community summaries."),
    }


@register(
    name="graph_lookup",
    description="Look up what the knowledge graph knows about a person, company, or topic "
                "(their relationships: who works where, who knows whom, competitors, etc.).",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
    category="memory",
)
async def graph_lookup(name: str):
    return graph.describe(name)


@register(
    name="graph_link",
    description="Record a relationship in the knowledge graph, e.g. link a person to a "
                "company, mark a competitor, or connect two people who know each other.",
    parameters={
        "type": "object",
        "properties": {
            "src": {"type": "string", "description": "Source entity name."},
            "rel": {"type": "string", "description": "Relation, e.g. works_at, knows, competitor_of, about."},
            "dst": {"type": "string", "description": "Destination entity name."},
            "src_type": {"type": "string", "enum": ["person", "company", "deal", "topic", "tool", "other"]},
            "dst_type": {"type": "string", "enum": ["person", "company", "deal", "topic", "tool", "other"]},
        },
        "required": ["src", "rel", "dst"],
    },
    category="memory",
)
async def graph_link(src: str, rel: str, dst: str, src_type: str = "other", dst_type: str = "other"):
    res = graph.add_relation(src, rel, dst, src_type=src_type, dst_type=dst_type)
    return res or {"error": "Could not create relation (empty names?)."}

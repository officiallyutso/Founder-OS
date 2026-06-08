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


@register(
    name="smart_recall",
    description="Deep CONNECTED recall: fuses hybrid (dense+sparse) text recall across ALL "
                "memory and documents WITH knowledge-graph relationships for the people/companies "
                "mentioned in the query or surfaced by the text. Use for questions that need BOTH "
                "what was said/written AND how entities relate — e.g. 'what do I know about Acme "
                "and who do I know there?', or multi-hop network+context questions. For pure text "
                "use deep_recall; for pure relationships use graph_lookup.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "description": "How many text passages to retrieve (default 8)."},
        },
        "required": ["query"],
    },
    category="memory",
)
async def smart_recall(query: str, limit: int = 8):
    try:
        limit = max(1, min(int(limit or 8), 16))
    except (TypeError, ValueError):
        limit = 8
    res = fused_recall(query, k=limit)
    return {
        "entities": res["entities"],
        "text": [{"collection": t["collection"], "text": (t["text"] or "")[:400]}
                 for t in res["text"]],
        "relations": [f"{r.get('src')} --{r.get('rel')}--> {r.get('dst')}"
                      for r in res["relations"]],
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

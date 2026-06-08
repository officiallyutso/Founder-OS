"""Local knowledge graph (GraphRAG-lite).

A relationship-aware memory layer on top of SQLite: entities (people, companies,
deals, topics) and typed relations between them. Flat vector search recalls
*text*; the graph recalls *structure* — "who works where", "who introduced whom",
"which deals touch this company". Built from the CRM and enriched from ingests.
No external services; everything is local.
"""
import json
import re
from datetime import datetime
from typing import Optional

from memory.sql_store import get_conn

# Cache of compiled entity matchers, invalidated when the entity table's
# (count, max updated_at) signature changes. Avoids rescanning/recompiling on
# every fused recall while still picking up nightly graph refreshes.
_entity_cache = None
_entity_cache_sig = None

_ATTR_KEYS = ("role", "company", "status", "email", "industry")
_TYPE_PRIORITY = {"person": 3, "company": 3, "deal": 2, "topic": 1, "tool": 1}


def init_graph_db():
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS kg_entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,            -- person | company | deal | topic | tool | other
            attrs_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, type)
        );

        CREATE TABLE IF NOT EXISTS kg_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            src_id INTEGER NOT NULL REFERENCES kg_entities(id),
            rel TEXT NOT NULL,             -- works_at | knows | competitor_of | about | etc.
            dst_id INTEGER NOT NULL REFERENCES kg_entities(id),
            weight REAL DEFAULT 1.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(src_id, rel, dst_id)
        );
        """
    )
    conn.commit()
    conn.close()


def upsert_entity(name: str, etype: str = "other", attrs: dict = None) -> Optional[int]:
    name = (name or "").strip()
    if not name:
        return None
    conn = get_conn()
    row = conn.execute(
        "SELECT id, attrs_json FROM kg_entities WHERE name = ? AND type = ?",
        (name, etype),
    ).fetchone()
    if row:
        eid = row["id"]
        if attrs:
            merged = {}
            try:
                merged = json.loads(row["attrs_json"] or "{}")
            except Exception:
                pass
            merged.update(attrs)
            conn.execute(
                "UPDATE kg_entities SET attrs_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(merged), datetime.now().isoformat(), eid),
            )
    else:
        cur = conn.execute(
            "INSERT INTO kg_entities (name, type, attrs_json) VALUES (?, ?, ?)",
            (name, etype, json.dumps(attrs or {})),
        )
        eid = cur.lastrowid
    conn.commit()
    conn.close()
    return eid


def add_relation(src_name: str, rel: str, dst_name: str,
                 src_type: str = "other", dst_type: str = "other", weight: float = 1.0):
    src_id = upsert_entity(src_name, src_type)
    dst_id = upsert_entity(dst_name, dst_type)
    if not src_id or not dst_id:
        return None
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO kg_relations (src_id, rel, dst_id, weight) VALUES (?, ?, ?, ?)",
            (src_id, rel, dst_id, weight),
        )
        conn.commit()
    finally:
        conn.close()
    return {"src": src_name, "rel": rel, "dst": dst_name}


def neighbors(name: str, limit: int = 25, by_weight: bool = False) -> list:
    """Return relations touching any entity matching `name` (in or out).

    Each row includes the relation `weight`. With `by_weight=True` the strongest
    relations come first (used by fused recall to keep the most salient edges
    when the output budget is tight).
    """
    conn = get_conn()
    q = f"%{name}%"
    order = "ORDER BY r.weight DESC" if by_weight else ""
    rows = conn.execute(
        f"""
        SELECT e1.name AS src, e1.type AS src_type, r.rel AS rel,
               e2.name AS dst, e2.type AS dst_type, r.weight AS weight
        FROM kg_relations r
        JOIN kg_entities e1 ON r.src_id = e1.id
        JOIN kg_entities e2 ON r.dst_id = e2.id
        WHERE e1.name LIKE ? OR e2.name LIKE ?
        {order}
        LIMIT ?
        """,
        (q, q, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def neighbors_2hop(name: str, first_limit: int = 10, second_limit: int = 3,
                   total_cap: int = 15) -> list:
    """Bounded two-hop expansion around `name`.

    Returns relations tagged with `hop` (1 = directly touches `name`, 2 = one
    step further out). Hard caps keep the fan-out small so multi-hop context
    stays useful instead of flooding the output budget.
    """
    out, seen = [], set()

    def _key(r):
        return (r.get("src"), r.get("rel"), r.get("dst"))

    first = neighbors(name, limit=first_limit, by_weight=True)
    frontier = []
    name_l = (name or "").lower()
    for r in first:
        k = _key(r)
        if k in seen:
            continue
        seen.add(k)
        out.append({**r, "hop": 1})
        for node in (r.get("src"), r.get("dst")):
            if node and name_l not in node.lower():
                frontier.append(node)

    for node in frontier:
        if len(out) >= total_cap:
            break
        for r in neighbors(node, limit=second_limit, by_weight=True):
            k = _key(r)
            if k in seen:
                continue
            seen.add(k)
            out.append({**r, "hop": 2})
            if len(out) >= total_cap:
                break
    return out[:total_cap]


def describe(name: str) -> str:
    """Human-readable summary of what the graph knows about `name`."""
    rels = neighbors(name)
    if not rels:
        return f"No graph knowledge about '{name}' yet."
    lines = [f"Graph knowledge near '{name}':"]
    for r in rels:
        lines.append(f"- {r['src']} ({r['src_type']}) --{r['rel']}--> {r['dst']} ({r['dst_type']})")
    return "\n".join(lines)


def _fmt_attrs(attrs_json) -> str:
    """Render the useful bits of an entity's attrs_json as a short string."""
    try:
        d = json.loads(attrs_json or "{}")
    except Exception:
        return ""
    return ", ".join(f"{k}={d[k]}" for k in _ATTR_KEYS if d.get(k))


def _entity_matcher(name: str):
    """Compile a word-boundary matcher for an entity name.

    Uses alnum lookarounds instead of \\b so it behaves with punctuation in
    names and never matches inside a longer word ('Ann' won't hit 'announce').
    """
    try:
        return re.compile(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])",
                          re.IGNORECASE)
    except re.error:
        return None


def _load_entities() -> list:
    """Load + cache entities as {name, type, attrs, _rx}, keyed by table signature."""
    global _entity_cache, _entity_cache_sig
    conn = get_conn()
    sig_row = conn.execute(
        "SELECT COUNT(*) AS c, MAX(updated_at) AS u FROM kg_entities").fetchone()
    sig = (sig_row["c"], sig_row["u"])
    if _entity_cache is not None and sig == _entity_cache_sig:
        conn.close()
        return _entity_cache
    rows = conn.execute("SELECT name, type, attrs_json FROM kg_entities").fetchall()
    conn.close()
    cache = []
    for r in rows:
        name = r["name"]
        if not name or len(name) < 3:
            continue
        rx = _entity_matcher(name)
        if rx is None:
            continue
        cache.append({"name": name, "type": r["type"],
                      "attrs": _fmt_attrs(r["attrs_json"]), "_rx": rx})
    _entity_cache, _entity_cache_sig = cache, sig
    return cache


def find_entities(text: str, limit: int = 8, query: str = None) -> list:
    """Return known graph entities mentioned in `text`, ranked by relevance.

    Bridges free text to the graph: match stored entity names with word
    boundaries (no substring false positives), then rank by whether the entity
    appears in the original `query` (strong signal), its type, and name
    specificity. Returns dicts of {name, type, attrs}. Used by
    `retrieval.fused_recall` to expand text recall with graph relationships.
    """
    if not (text or "").strip():
        return []
    query = query or ""
    scored = []
    for e in _load_entities():
        if not e["_rx"].search(text):
            continue
        in_query = bool(query and e["_rx"].search(query))
        type_pri = _TYPE_PRIORITY.get(e["type"], 1)
        score = (3 if in_query else 0) + type_pri + min(len(e["name"]) / 10.0, 2.0)
        scored.append((score, e))
    scored.sort(key=lambda se: se[0], reverse=True)
    return [{"name": e["name"], "type": e["type"], "attrs": e["attrs"]}
            for _, e in scored[:limit]]


def build_from_crm() -> dict:
    """Seed/refresh the graph from CRM contacts and companies."""
    from memory.sql_store import get_all_contacts
    contacts = get_all_contacts()
    people = companies = links = 0
    for c in contacts:
        name = c.get("name")
        if not name:
            continue
        upsert_entity(name, "person",
                      {"email": c.get("email"), "role": c.get("role"),
                       "status": c.get("status")})
        people += 1
        comp = c.get("company")
        if comp:
            upsert_entity(comp, "company")
            companies += 1
            add_relation(name, "works_at", comp, "person", "company")
            links += 1
            if c.get("role"):
                add_relation(name, f"role:{c['role']}", comp, "person", "company")
    return {"people": people, "company_links": links}


init_graph_db()

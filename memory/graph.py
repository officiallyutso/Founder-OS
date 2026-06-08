"""Local knowledge graph (GraphRAG-lite).

A relationship-aware memory layer on top of SQLite: entities (people, companies,
deals, topics) and typed relations between them. Flat vector search recalls
*text*; the graph recalls *structure* — "who works where", "who introduced whom",
"which deals touch this company". Built from the CRM and enriched from ingests.
No external services; everything is local.
"""
import json
from datetime import datetime
from typing import Optional

from memory.sql_store import get_conn


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


def neighbors(name: str, limit: int = 25) -> list:
    """Return relations touching any entity matching `name` (in or out)."""
    conn = get_conn()
    q = f"%{name}%"
    rows = conn.execute(
        """
        SELECT e1.name AS src, e1.type AS src_type, r.rel AS rel,
               e2.name AS dst, e2.type AS dst_type
        FROM kg_relations r
        JOIN kg_entities e1 ON r.src_id = e1.id
        JOIN kg_entities e2 ON r.dst_id = e2.id
        WHERE e1.name LIKE ? OR e2.name LIKE ?
        LIMIT ?
        """,
        (q, q, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def describe(name: str) -> str:
    """Human-readable summary of what the graph knows about `name`."""
    rels = neighbors(name)
    if not rels:
        return f"No graph knowledge about '{name}' yet."
    lines = [f"Graph knowledge near '{name}':"]
    for r in rels:
        lines.append(f"- {r['src']} ({r['src_type']}) --{r['rel']}--> {r['dst']} ({r['dst_type']})")
    return "\n".join(lines)


def find_entities(text: str, limit: int = 10) -> list:
    """Return known graph entities whose name appears in `text`.

    A dependency-free way to bridge free text to the graph: scan stored entity
    names and keep those that occur (case-insensitive) in the text. Short names
    (<3 chars) are ignored to avoid spurious substring hits. Used by
    `retrieval.fused_recall` to expand text recall with graph relationships.
    """
    text_l = (text or "").lower()
    if not text_l.strip():
        return []
    conn = get_conn()
    rows = conn.execute("SELECT name, type FROM kg_entities").fetchall()
    conn.close()
    seen, out = set(), []
    for r in rows:
        name = r["name"]
        if not name or len(name) < 3:
            continue
        if name.lower() in text_l and name not in seen:
            seen.add(name)
            out.append({"name": name, "type": r["type"]})
        if len(out) >= limit:
            break
    return out


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

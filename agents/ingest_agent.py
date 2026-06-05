"""Ingestion agent — the auto-capture brain.

Takes ANY inbound content (plain text, scraped link content, or an image
description) and uses the LLM to:
  1. Decide whether it is knowledge worth persisting.
  2. Classify it (company / competitor / research / contact / task / idea / note).
  3. Extract structured entities.
  4. Store it in the right place (SQL tables + vector memory) for later recall.
  5. Produce a short, useful reply for the founder.

This is what makes "send anything, it understands and files it" work.
"""
import json
import logging

from llm.router import complete
from memory.vector_store import add as vec_add
from memory.sql_store import (
    add_company, search_companies, add_contact, add_task, add_note,
)

logger = logging.getLogger(__name__)

CATEGORIES = [
    "company_info", "competitor", "research", "contact",
    "task", "idea", "note",
]

# Which vector collection each category lands in for semantic search.
_COLLECTION_FOR = {
    "company_info": "research",
    "competitor": "research",
    "research": "research",
    "contact": "notes",
    "task": "notes",
    "idea": "notes",
    "note": "notes",
}


async def ingest(content: str, context: str = "", source_type: str = "text") -> dict:
    """Classify, store, and summarize arbitrary content.

    Returns a dict: {stored, category, title, summary, entities, reply}
    """
    messages = [
        {"role": "system", "content": (
            "You are the knowledge-ingestion engine for a startup founder's "
            "operating system. You receive whatever the founder sends (notes, "
            "links they've shared, articles, screenshots described in text, "
            "competitor info, contacts, ideas, tasks). Classify it, extract "
            "structured data, and decide if it's worth saving to long-term "
            "memory. Always be accurate; never invent facts not present."
        )},
        {"role": "user", "content": f"""Analyze and classify this content.

CATEGORIES (pick the single best fit):
- company_info: info about a company (could be a customer, partner, or target)
- competitor: info about a competitor or rival product
- research: a research topic, market insight, trend, article, or reference link
- contact: a specific person to remember (name + ideally role/company/email)
- task: a to-do or action item for the founder
- idea: a product/business idea or hypothesis
- note: anything else worth remembering

EXISTING CONTEXT FROM MEMORY (may be empty):
{context or "(none)"}

CONTENT TO INGEST:
{content}

Respond ONLY with JSON in this exact shape:
{{
  "is_knowledge": true,
  "category": "one of the categories above",
  "title": "short title (max 8 words)",
  "summary": "concise factual summary of the content (1-4 sentences)",
  "entities": {{
    "company": "",
    "person": "",
    "role": "",
    "email": "",
    "url": "",
    "industry": ""
  }},
  "tags": ["", ""],
  "reply": "A short, helpful reply to the founder: confirm what you captured and add one useful insight, question, or next step. Use plain text."
}}
Set is_knowledge=false ONLY if this is purely conversational with nothing worth saving.
Only output JSON, nothing else."""}
    ]

    raw = await complete(messages, task_type="analysis", max_tokens=900)
    clean = raw.strip().replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(clean)
    except Exception:
        logger.warning("Ingest classification parse failed; storing as raw note.")
        data = {
            "is_knowledge": True,
            "category": "note",
            "title": content[:50],
            "summary": content[:500],
            "entities": {},
            "tags": [source_type],
            "reply": "Saved that to memory.",
        }

    if not data.get("is_knowledge", True):
        return {
            "stored": False,
            "category": data.get("category", "note"),
            "title": data.get("title", ""),
            "summary": data.get("summary", ""),
            "entities": data.get("entities", {}),
            "reply": data.get("reply", ""),
        }

    category = data.get("category", "note")
    if category not in CATEGORIES:
        category = "note"
    title = data.get("title", "") or content[:50]
    summary = data.get("summary", "") or content[:500]
    entities = data.get("entities", {}) or {}
    tags = data.get("tags", []) or []
    tag_str = ",".join([str(t) for t in tags] + [source_type, f"category:{category}"])

    stored_where = []

    # ── Route to structured storage by category ───────────────────────────────
    try:
        if category in ("company_info", "competitor"):
            company_name = entities.get("company") or title
            if company_name and not search_companies(company_name):
                add_company(
                    name=company_name,
                    industry=entities.get("industry"),
                    description=summary,
                    research_summary=json.dumps({
                        "category": category, "summary": summary,
                        "entities": entities, "source": source_type,
                    }),
                    notes=f"Auto-captured via Telegram ({source_type}). Category: {category}.",
                )
                stored_where.append(f"companies ({company_name})")
            else:
                stored_where.append("companies (already known)")

        elif category == "contact":
            person = entities.get("person")
            if person:
                add_contact(
                    name=person,
                    company=entities.get("company"),
                    role=entities.get("role"),
                    email=entities.get("email"),
                    source=f"telegram_{source_type}",
                )
                stored_where.append(f"contacts ({person})")

        elif category == "task":
            add_task(title=title or summary[:100])
            stored_where.append("tasks")

        # Idea / research / note (and anything above) also land in notes for recall.
        if category in ("idea", "research", "note") or not stored_where:
            add_note(content=f"{title}\n{summary}".strip(), tags=tag_str)
            stored_where.append("notes")
    except Exception as e:
        logger.error(f"Ingest structured storage error: {e}")

    # ── Always index in vector memory for semantic recall ─────────────────────
    collection = _COLLECTION_FOR.get(category, "notes")
    try:
        vec_add(
            collection,
            f"{title}\n{summary}\n{content[:1500]}",
            metadata={
                "category": category,
                "title": title,
                "source": f"telegram_{source_type}",
                "tags": tag_str,
            },
        )
        stored_where.append(f"vector:{collection}")
    except Exception as e:
        logger.error(f"Ingest vector storage error: {e}")

    return {
        "stored": True,
        "category": category,
        "title": title,
        "summary": summary,
        "entities": entities,
        "reply": data.get("reply", "Captured and filed."),
        "stored_where": stored_where,
    }

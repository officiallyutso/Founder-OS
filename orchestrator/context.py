from memory.vector_store import search_all
from memory.sql_store import search_contacts, search_companies, get_recent_outreach
import json

async def build_context(message: str, intent: str, entities: dict) -> str:
    """Build a rich context string to inject into LLM prompts."""
    sections = []

    # Semantic memory search
    memory_results = search_all(message, n_results=4)
    if memory_results:
        mem_texts = [f"- [{r['collection']}] {r['text'][:200]}" for r in memory_results]
        sections.append("RELEVANT MEMORY:\n" + "\n".join(mem_texts))

    # CRM context based on entities
    if entities.get("company"):
        companies = search_companies(entities["company"])
        if companies:
            c = companies[0]
            sections.append(f"CRM COMPANY CONTEXT:\nName: {c['name']}\nDescription: {c.get('description', '')}\nResearch: {c.get('research_summary', '')[:300]}")

    if entities.get("person") or entities.get("contact"):
        name = entities.get("person") or entities.get("contact")
        contacts = search_contacts(name)
        if contacts:
            c = contacts[0]
            sections.append(f"CRM CONTACT CONTEXT:\nName: {c['name']}, Role: {c.get('role', '')}, Company: {c.get('company', '')}, Status: {c.get('status', '')}, Notes: {c.get('notes', '')}")

    # Recent outreach for outreach-related intents
    if intent in ["draft_outreach", "send_email", "get_followups", "pipeline_status"]:
        recent = get_recent_outreach(days=14)
        if recent:
            lines = [f"- {r.get('contact_name', '?')} via {r['channel']} ({r['sent_at'][:10]}): {r.get('subject', '')}" for r in recent[:5]]
            sections.append("RECENT OUTREACH (14 days):\n" + "\n".join(lines))

    return "\n\n".join(sections) if sections else ""

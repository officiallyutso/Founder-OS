from llm.router import complete
from memory.sql_store import get_contact, search_contacts, search_companies
from memory.vector_store import search as mem_search
from config import config
import json

async def draft_email(contact_name: str = None, contact_id: int = None,
                      company_name: str = None, custom_context: str = "") -> dict:
    """Generate a personalized outreach email."""

    contact = None
    company_summary = ""

    if contact_id:
        contact = get_contact(contact_id)
    elif contact_name:
        results = search_contacts(contact_name)
        if results:
            contact = results[0]

    if company_name or (contact and contact.get("company")):
        cn = company_name or contact.get("company")
        companies = search_companies(cn)
        if companies and companies[0].get("research_summary"):
            try:
                cs = json.loads(companies[0]["research_summary"])
                company_summary = json.dumps(cs, indent=2)
            except Exception:
                company_summary = companies[0].get("research_summary", "")

    # Build personalization context
    contact_info = ""
    if contact:
        contact_info = f"""
Contact Name: {contact.get('name')}
Role: {contact.get('role', 'Unknown')}
Company: {contact.get('company', 'Unknown')}
LinkedIn: {contact.get('linkedin_url', '')}
Previous Notes: {contact.get('notes', '')}
"""

    messages = [
        {"role": "system", "content": f"""You are a cold outreach expert helping {config.my_name}, {config.my_role} at {config.company_name}.
{config.company_name}: {config.my_one_liner}

Write short, human, personalized cold emails. No fluff. No generic openers.
Max 5 sentences. End with a single, low-friction CTA."""},
        {"role": "user", "content": f"""Draft a cold outreach email.

SENDER:
Name: {config.my_name}
Role: {config.my_role}
Company: {config.company_name}
What we do: {config.my_one_liner}

RECIPIENT:
{contact_info if contact_info else f"Name: {contact_name or 'Unknown'}, Company: {company_name or 'Unknown'}"}

COMPANY RESEARCH:
{company_summary[:1500] if company_summary else "No research available yet. Use general personalization."}

ADDITIONAL CONTEXT:
{custom_context}

Respond in this exact JSON format:
{{
  "subject": "",
  "body": "",
  "linkedin_variant": "",
  "personalization_notes": ""
}}
Only output JSON."""}
    ]

    raw = await complete(messages, task_type="outreach")
    clean = raw.strip().replace("```json", "").replace("```", "").strip()

    try:
        draft = json.loads(clean)
    except Exception:
        draft = {"subject": "Following up", "body": raw[:1000], "linkedin_variant": "", "personalization_notes": ""}

    # Attach recipient details so the email can actually be sent later.
    draft["to_email"] = contact.get("email") if contact else None
    draft["contact_name"] = contact.get("name") if contact else (contact_name or "")
    draft["company_name"] = (contact.get("company") if contact else None) or company_name or ""
    return draft

async def draft_linkedin_message(contact_name: str, company_name: str = "", context: str = "") -> str:
    """Draft a short LinkedIn connection request note (300 char limit)."""
    messages = [
        {"role": "system", "content": f"You write LinkedIn connection request notes for {config.my_name} at {config.company_name}. Max 280 characters. Human, specific, no buzzwords."},
        {"role": "user", "content": f"Write a LinkedIn note to {contact_name} at {company_name}. Context: {context or config.my_one_liner}. Only output the note text, nothing else."}
    ]
    result = await complete(messages, task_type="outreach", max_tokens=100)
    return result.strip()[:300]

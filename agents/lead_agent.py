"""Lead-generation agent.

Two modes, both free (no paid data providers):

  A) Company mode — "find contacts at Acme": research the company, discover its
     key people, then enrich each with email / LinkedIn / phone.

  B) Named-people mode — "ashutosh bisht, priyansh negi of predco ai, email
     linkedin phone": enrich the exact people you named.

A request is parsed by the LLM (parse_lead_request) so ANY phrasing works —
"at", "of", "from", "for", a bare list of names, role-based ("their head of
sales"), etc.
"""
import json
import logging

from agents.research_agent import research_company
from memory.sql_store import add_contact, search_contacts
from tools import contact_finder as cf
from tools.web_search import search
from llm.router import complete

logger = logging.getLogger(__name__)


async def parse_lead_request(message: str) -> dict:
    """Use the LLM to extract who/where to find contacts for, from any phrasing."""
    messages = [
        {"role": "system", "content": (
            "You extract structured lead-generation requests from a founder's "
            "message. People may be listed in any format; the company may be "
            "introduced with 'at', 'of', 'from', 'for', etc.")},
        {"role": "user", "content": f"""Message:
{message}

Extract JSON ONLY:
{{
  "company": "company name if mentioned, else empty string",
  "people": ["each explicit person's full name mentioned, else empty list"],
  "role": "a target job title/role if they want decision-makers by role (e.g. 'head of sales'), else empty string",
  "fields": ["which of email/phone/linkedin they asked for; if unspecified use all three"]
}}
Only output JSON."""}
    ]
    try:
        raw = await complete(messages, task_type="general", max_tokens=300)
        clean = raw.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(clean)
    except Exception as e:
        logger.warning(f"parse_lead_request failed: {e}")
        data = {}
    return {
        "company": (data.get("company") or "").strip(),
        "people": [p.strip() for p in (data.get("people") or []) if p and p.strip()],
        "role": (data.get("role") or "").strip(),
        "fields": data.get("fields") or ["email", "phone", "linkedin"],
    }


def _coerce_summary(research_result: dict) -> dict:
    summary = research_result.get("summary", {})
    if isinstance(summary, str):
        try:
            summary = json.loads(summary)
        except Exception:
            summary = {}
    return summary or {}


async def _enrich_person(name: str, company: str, domain: str, linkedin_hint: str = "") -> dict:
    """Find a single person's email, LinkedIn, and phone via free web search + patterns."""
    emails, phones = [], []
    linkedin = linkedin_hint or ""

    queries = []
    if company:
        queries = [f'"{name}" {company} email',
                   f'{name} {company} linkedin',
                   f'{name} {company} contact phone']
    else:
        queries = [f'"{name}" email contact', f'{name} linkedin']

    for q in queries:
        try:
            for r in search(q, num_results=4):
                url = r.get("url", "") or ""
                blob = f"{r.get('title','')} {r.get('snippet','')}"
                for e in cf.extract_emails(blob):
                    if e not in emails:
                        emails.append(e)
                for p in cf.extract_phones(blob):
                    if p not in phones:
                        phones.append(p)
                if "linkedin.com/in" in url and not linkedin:
                    linkedin = url
        except Exception as e:
            logger.debug(f"enrich search failed '{q}': {e}")

    guessed = cf.guess_email_patterns(name, domain) if domain else []
    best_email = emails[0] if emails else (guessed[0] if guessed else None)
    confidence = "verified (found online)" if emails else (
        "best guess" if guessed else "not found")

    return {
        "name": name,
        "linkedin": linkedin,
        "email": best_email,
        "email_confidence": confidence,
        "email_guesses": guessed[:4],
        "web_emails": emails,
        "phones": phones[:3],
    }


async def find_leads(company: str = None, role: str = None,
                     people: list = None, max_people: int = 8) -> dict:
    """Discover contactable leads. Works from a company, explicit names, or a role."""
    company = (company or "").strip()
    people = people or []
    logger.info(f"[Leads] company={company!r} role={role!r} people={people}")

    website = ""
    key_people = []
    if company:
        research = await research_company(company)
        summary = _coerce_summary(research)
        website = summary.get("website", "")
        key_people = summary.get("key_people", []) or []

    domain = cf.find_company_domain(company, website=website) if company else ""
    mx_ok = cf.domain_has_mx(domain) if domain else None
    generic = cf.scrape_company_contacts(domain) if domain else {"emails": [], "phones": []}

    # Decide the target list of people.
    if people:
        targets = [{"name": n, "role": role, "linkedin": ""} for n in people]
    else:
        targets = key_people
        if role and key_people:
            matched = [p for p in key_people if role.lower() in (p.get("role", "") or "").lower()]
            if matched:
                targets = matched
            else:
                # Try to discover a name for the requested role.
                for r in search(f"{company} {role} name linkedin", num_results=3):
                    cand = r.get("title", "").split(" - ")[0].split(" | ")[0].strip()
                    if 2 <= len(cand.split()) <= 4:
                        targets = [{"name": cand, "role": role, "linkedin": r.get("url", "")}]
                        break

    leads = []
    for person in targets[:max_people]:
        name = (person.get("name") or "").strip()
        if not name or name.lower() in ("n/a", "unknown"):
            continue
        info = await _enrich_person(name, company, domain, person.get("linkedin", ""))
        info["role"] = person.get("role") or role

        # Store in CRM (skip exact name+company duplicate).
        dup = [c for c in search_contacts(name)
               if (c.get("company") or "").lower() == company.lower()]
        if not dup:
            add_contact(
                name=name, company=company or None, role=info.get("role"),
                email=info.get("email"), linkedin_url=info.get("linkedin"),
                phone=info["phones"][0] if info.get("phones") else None,
                source="lead_gen",
                notes=f"Auto-found lead. Email confidence: {info['email_confidence']}. "
                      f"Guesses: {', '.join(info.get('email_guesses', [])[:3])}",
            )
        leads.append(info)

    return {
        "company": company,
        "domain": domain,
        "website": website,
        "domain_accepts_mail": mx_ok,
        "company_emails": generic.get("emails", []),
        "company_phones": generic.get("phones", []),
        "leads": leads,
    }

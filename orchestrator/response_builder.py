from orchestrator.router import classify_intent
from orchestrator.context import build_context
from agents.research_agent import research_company
from agents.outreach_agent import draft_email, draft_linkedin_message
from agents.memory_agent import save as mem_save, recall
from agents.crm_agent import (
    add as crm_add, update_status, get_followups,
    pipeline, search as crm_search, set_followup
)
from agents.report_agent import daily_briefing
from agents.ingest_agent import ingest
from agents.lead_agent import find_leads, parse_lead_request
from agents.reasoning_agent import deep_reason
from memory.sql_store import add_task, get_pending_tasks
from memory.vector_store import add as vec_add
from llm.router import complete
from tools.utils import format_contact, extract_urls
from tools.scraper import scrape_url
from outreach.email_sender import send_email
from outreach.tracker import mark_sent
from config import config
import re
import json

# Intents that are explicit commands — handled directly. Everything else flows
# through the auto-ingest path so it gets understood, classified, and stored.
COMMAND_INTENTS = {
    "research_company", "find_contacts", "draft_outreach", "add_contact",
    "update_contact", "get_followups", "pipeline_status", "search_memory",
    "add_task", "get_tasks", "daily_report", "send_email",
}

# Last drafted email, kept so a follow-up "send" can dispatch it. The bot is
# single-user (only the authorized Telegram user), so a module-level slot is fine.
_pending_draft = {}

_EMAIL_IN_TEXT = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def _scrape_links(message: str) -> str:
    """Find URLs in the message, scrape them, and return a readable context block."""
    urls = extract_urls(message)
    blocks = []
    for url in urls[:3]:
        scraped = scrape_url(url, max_chars=4000)
        if scraped.get("error"):
            blocks.append(f"URL: {url}\n[Could not read: {scraped['error']}]")
        else:
            blocks.append(
                f"URL: {url}\nTitle: {scraped.get('title', '')}\n"
                f"Content: {scraped.get('text', '')}"
            )
    return "\n\n".join(blocks)


async def process_message(message: str, image_context: str = "") -> str:
    """Main entry point: process a user message and return a response string.

    `image_context` is a textual understanding of any attached image (from the
    vision layer). Links inside the message are scraped automatically.
    """
    global _pending_draft

    # ── Enrich the message with scraped link content + image understanding ────
    link_context = _scrape_links(message)
    enriched = message
    if image_context:
        enriched += f"\n\n[IMAGE CONTENT]\n{image_context}"
    if link_context:
        enriched += f"\n\n[LINK CONTENT]\n{link_context}"

    classified = await classify_intent(message)
    intent = classified.get("intent", "general_chat")
    entities = classified.get("entities", {})

    _safe_print(f"[Orchestrator] Intent: {intent} | Entities: {entities} | "
                f"links={bool(link_context)} image={bool(image_context)}")

    # Store the full (enriched) conversation in memory
    vec_add("conversations", enriched, metadata={"role": "user", "intent": intent})

    try:

        # ── AUTO-INGEST (default path for any non-command message) ────────────
        # Anything that isn't an explicit command gets understood, classified,
        # and stored automatically — text, shared links, or image content.
        if intent not in COMMAND_INTENTS:
            return await _ingest_and_reply(enriched, intent, entities)

        # ── RESEARCH ──────────────────────────────────────────────────────────
        if intent == "research_company":
            company = entities.get("company") or _extract_after(message, ["research", "about", "find info on"])
            if not company:
                return "Which company should I research? Just say: *research [company name]*"
            await message_status(f"🔍 Researching {company}...")
            result = await research_company(company)
            s = result.get("summary", {})
            if isinstance(s, str):
                return s
            lines = [
                f"*{s.get('name', company)}*",
                f"_{s.get('what_they_do', '')}_",
                "",
                f"🏭 Industry: {s.get('industry', '?')}",
                f"📍 Location: {s.get('location', '?')}",
                f"👥 Size: {s.get('size', '?')}",
                f"🌐 Website: {s.get('website', '?')}",
                "",
            ]
            if s.get("key_people"):
                lines.append("*Key People:*")
                for p in s["key_people"][:4]:
                    lines.append(f"  • {p.get('name')} — {p.get('role', '')}")
            if s.get("outreach_angle"):
                lines.append(f"\n💡 *Outreach angle:* {s['outreach_angle']}")
            return "\n".join(lines)

        # ── FIND CONTACTS / LEAD GEN ──────────────────────────────────────────
        elif intent == "find_contacts":
            req = await parse_lead_request(message)
            company = req.get("company", "")
            people = req.get("people", [])
            role = req.get("role", "") or entities.get("role")
            if not company and not people:
                return ("Tell me who or where to look. Examples:\n"
                        "• *find contacts at HDFC Ergo*\n"
                        "• *get me the head of sales at Acme*\n"
                        "• *email, linkedin, phone of Jane Doe, John Roe of Predco AI*")
            target_desc = ", ".join(people) if people else (f"{role} at {company}" if role else company)
            await message_status(f"🕵️ Finding contacts for {target_desc}...")
            result = await find_leads(company=company, role=role, people=people)
            return await _present_leads(result)

        # ── DRAFT OUTREACH ────────────────────────────────────────────────────
        elif intent == "draft_outreach":
            contact_name = entities.get("person") or entities.get("contact")
            company_name = entities.get("company")
            draft = await draft_email(contact_name=contact_name, company_name=company_name, custom_context=message)

            # Remember it so "send" can dispatch it.
            _pending_draft = {
                "subject": draft.get("subject", ""),
                "body": draft.get("body", ""),
                "to_email": draft.get("to_email"),
                "contact_name": draft.get("contact_name", ""),
                "company_name": draft.get("company_name", ""),
            }

            lines = [
                f"*Draft Email*",
                f"To: {draft.get('to_email') or '(no email on file)'}",
                f"Subject: {draft.get('subject', '')}",
                "",
                draft.get("body", ""),
                "",
                "---",
                f"*LinkedIn variant:*",
                draft.get("linkedin_variant", ""),
                "",
                f"_{draft.get('personalization_notes', '')}_",
                "",
            ]
            if draft.get("to_email"):
                lines.append(f"Reply *send* to email this to {draft['to_email']}, or give feedback to revise.")
            else:
                lines.append("I don't have their email. Reply *send to name@company.com* to send, or give feedback to revise.")
            return "\n".join(lines)

        # ── SEND EMAIL ────────────────────────────────────────────────────────
        elif intent == "send_email":
            if not _pending_draft or not _pending_draft.get("body"):
                return ("Nothing drafted yet. First say e.g. "
                        "*draft email to Jane at Acme*, then reply *send*.")

            # Allow overriding/supplying the recipient inline: "send to x@y.com".
            override = _EMAIL_IN_TEXT.search(message)
            to_email = override.group(0) if override else _pending_draft.get("to_email")
            if not to_email:
                return ("I don't have a recipient email for this draft. "
                        "Reply: *send to their@email.com*")

            await message_status(f"📤 Sending to {to_email}...")
            result = send_email(
                to_address=to_email,
                subject=_pending_draft.get("subject", "(no subject)"),
                body=_pending_draft.get("body", ""),
            )
            if not result.get("success"):
                return f"⚠️ Couldn't send: {result.get('error', 'unknown error')}"

            # Log it + advance CRM status if we know the contact.
            name = _pending_draft.get("contact_name")
            if name:
                try:
                    mark_sent(name, channel="email",
                              subject=_pending_draft.get("subject"),
                              body=_pending_draft.get("body"))
                except Exception as e:
                    print(f"[send_email] tracker log failed: {e}")
            sent_to = to_email
            _pending_draft = {}
            return (f"✅ Email sent to {sent_to}.\n"
                    f"Logged it and set a 3-day follow-up reminder.")

        # ── ADD CONTACT ───────────────────────────────────────────────────────
        elif intent == "add_contact":
            name = entities.get("person") or entities.get("name")
            if not name:
                return "Who should I add? Try: *add John Smith, Head of Claims at HDFC Ergo, john@hdfc.com*"
            result = await crm_add(
                name=name,
                company=entities.get("company"),
                role=entities.get("role"),
                email=entities.get("email"),
                linkedin_url=entities.get("linkedin_url"),
            )
            return f"✅ {result['message']} (ID: {result['contact_id']})"

        # ── UPDATE CONTACT ────────────────────────────────────────────────────
        elif intent == "update_contact":
            contact = entities.get("person") or entities.get("contact")
            status = entities.get("status")
            if contact and status:
                result = await update_status(contact, status)
                return f"✅ {result.get('message', result.get('error', ''))}"
            return "Try: *mark [name] as responded* or *update [name] status to meeting_set*"

        # ── GET FOLLOWUPS ─────────────────────────────────────────────────────
        elif intent == "get_followups":
            contacts = await get_followups()
            if not contacts:
                return "✅ No follow-ups due right now. You're on top of it."
            lines = [f"*{len(contacts)} follow-ups due:*", ""]
            for c in contacts[:10]:
                lines.append(format_contact(c))
                lines.append("")
            return "\n".join(lines)

        # ── PIPELINE STATUS ───────────────────────────────────────────────────
        elif intent == "pipeline_status":
            return await pipeline()

        # ── SAVE NOTE ─────────────────────────────────────────────────────────
        elif intent == "save_note":
            content = message.replace("note:", "").replace("remember that", "").replace("remember", "").strip()
            result = await mem_save(content, source="user_note")
            return f"✅ Saved to memory: _{content[:80]}_"

        # ── SEARCH MEMORY ─────────────────────────────────────────────────────
        elif intent == "search_memory":
            query = entities.get("query") or message
            results = await recall(query)
            if not results:
                return f"Nothing found in memory for: _{query}_"
            lines = [f"*Memory search: {query}*", ""]
            for r in results:
                lines.append(f"[{r['collection']}] {r['text'][:200]}")
                lines.append("")
            return "\n".join(lines)

        # ── ADD TASK ──────────────────────────────────────────────────────────
        elif intent == "add_task":
            title = entities.get("title") or message.replace("todo:", "").replace("task:", "").replace("remind me to", "").strip()
            task_id = add_task(title=title)
            return f"✅ Task added: _{title}_ (ID: {task_id})"

        # ── GET TASKS ─────────────────────────────────────────────────────────
        elif intent == "get_tasks":
            tasks = get_pending_tasks()
            if not tasks:
                return "✅ No pending tasks. Clear queue!"
            lines = [f"*{len(tasks)} pending tasks:*", ""]
            for t in tasks[:10]:
                priority_icon = "🔴" if t["priority"] == 1 else "🟡" if t["priority"] == 2 else "🟢"
                due = f" (due {t['due_at'][:10]})" if t.get("due_at") else ""
                lines.append(f"{priority_icon} {t['title']}{due}")
            return "\n".join(lines)

        # ── DAILY REPORT ──────────────────────────────────────────────────────
        elif intent == "daily_report":
            await message_status("📊 Generating your briefing...")
            return await daily_briefing()

        # ── FALLBACK (any unrecognized command) ───────────────────────────────
        else:
            return await _ingest_and_reply(enriched, intent, entities)

    except Exception as e:
        import traceback
        _safe_print(f"[Orchestrator Error] {e}\n{traceback.format_exc()}")
        return f"⚠️ Something went wrong: {str(e)[:200]}\n\nTry rephrasing or check the logs."

# Helpers
async def _ingest_and_reply(enriched: str, intent: str, entities: dict) -> str:
    """Auto-classify + store the content, then craft a useful reply."""
    context = await build_context(enriched, intent, entities)
    result = await ingest(enriched, context=context, source_type="text")
    reply = (result.get("reply") or "").strip()

    if result.get("stored"):
        category = result.get("category", "note").replace("_", " ")
        title = result.get("title", "")
        header = f"🗂 *Captured* — _{category}_"
        if title:
            header += f": {title}"
        if reply:
            vec_add("conversations", reply, metadata={"role": "assistant"})
            return f"{header}\n\n{reply}"
        return header

    # Not knowledge worth storing → a context-aware conversational reply.
    # Trivial messages get a quick single-pass answer; anything substantive runs
    # through the full multi-step agentic reasoning pipeline.
    stripped = enriched.strip()
    is_trivial = len(stripped) < 15 and "?" not in stripped
    if is_trivial:
        messages = [
            {"role": "system", "content": f"""You are the personal AI operating system for {config.my_name}, {config.my_role} at {config.company_name}.
{config.company_name}: {config.my_one_liner}
Be direct, smart, and immediately useful. Use Telegram markdown (* bold, _ italic).

{f"CONTEXT FROM MEMORY:{chr(10)}{context}" if context else ""}"""},
            {"role": "user", "content": enriched}
        ]
        response = await complete(messages, task_type="general")
    else:
        response = await deep_reason(enriched, context=context)

    vec_add("conversations", response, metadata={"role": "assistant"})
    return response

async def _present_leads(result: dict) -> str:
    """Factual lead block + a short, varied LLM-written intro (dynamic phrasing)."""
    body = _format_leads(result)
    leads = result.get("leads", [])
    found = sum(1 for L in leads if L.get("email") or L.get("phones") or L.get("linkedin"))
    try:
        intro = await complete([
            {"role": "system", "content":
                "You are a founder's assistant. Write ONE short, natural, varied "
                "sentence introducing the lead results below. Don't repeat data, "
                "don't use the same template every time. Plain text, no markdown."},
            {"role": "user", "content":
                f"Company/target: {result.get('company') or 'the named people'}. "
                f"People found: {found}/{len(leads)}. "
                f"Domain: {result.get('domain') or 'unknown'}. Write the one-liner."},
        ], task_type="general", max_tokens=80)
        intro = (intro or "").strip()
        if intro:
            return f"{intro}\n\n{body}"
    except Exception:
        pass
    return body


def _format_leads(r: dict) -> str:
    company = r.get("company", "")
    lines = [f"*Leads — {company}*"]
    if r.get("domain"):
        mx = r.get("domain_accepts_mail")
        mx_note = " ✅" if mx else (" ⚠️ no mail server" if mx is False else "")
        lines.append(f"🌐 Domain: {r['domain']}{mx_note}")
    lines.append("")

    company_emails = r.get("company_emails", [])
    company_phones = r.get("company_phones", [])
    if company_emails:
        lines.append("*Company emails (verified from site):*")
        for e in company_emails[:8]:
            lines.append(f"  • {e}")
    if company_phones:
        lines.append("*Company phones (from site):*")
        for p in company_phones[:5]:
            lines.append(f"  • {p}")
    if company_emails or company_phones:
        lines.append("")

    leads = r.get("leads", [])
    if leads:
        lines.append(f"*People ({len(leads)}):*")
        for L in leads:
            lines.append(f"\n👤 *{L.get('name','')}* — {L.get('role','') or '?'}")
            if L.get("email"):
                lines.append(f"   ✉️ {L['email']}  _({L.get('email_confidence','')})_")
            if L.get("email_guesses") and L.get("email_confidence") != "verified (found online)":
                others = [g for g in L['email_guesses'][1:3]]
                if others:
                    lines.append(f"   ↳ other guesses: {', '.join(others)}")
            if L.get("phones"):
                lines.append(f"   📞 {', '.join(L['phones'][:2])}")
            if L.get("linkedin"):
                lines.append(f"   🔗 {L['linkedin']}")
    elif not (company_emails or company_phones):
        lines.append("Couldn't find public contacts. Try giving me the company "
                     "website, or a specific person's name + company.")

    lines.append("\n_Saved to your CRM. Say_ *draft email to [name]* _to reach out._")
    lines.append("_Note: 'best guess' emails are pattern-based — verify before sending._")
    return "\n".join(lines)


def _extract_after(text: str, keywords: list) -> str:
    text_lower = text.lower()
    for kw in keywords:
        idx = text_lower.find(kw)
        if idx != -1:
            return text[idx + len(kw):].strip()
    return ""

def _safe_print(text: str):
    """Print without ever crashing on consoles that can't encode emoji."""
    try:
        print(text)
    except Exception:
        try:
            print(text.encode("ascii", "replace").decode("ascii"))
        except Exception:
            pass

async def message_status(text: str):
    """Placeholder — bot handlers will send typing indicator instead."""
    _safe_print(f"[Status] {text}")

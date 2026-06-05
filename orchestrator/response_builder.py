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
from memory.sql_store import add_task, get_pending_tasks
from memory.vector_store import add as vec_add
from llm.router import complete
from tools.utils import format_contact, truncate
from config import config
import json

async def process_message(message: str) -> str:
    """Main entry point: process a user message and return a response string."""

    classified = await classify_intent(message)
    intent = classified.get("intent", "general_chat")
    entities = classified.get("entities", {})

    print(f"[Orchestrator] Intent: {intent} | Entities: {entities}")

    # Store conversation in memory
    vec_add("conversations", message, metadata={"role": "user", "intent": intent})

    try:

        # ── RESEARCH ──────────────────────────────────────────────────────────
        if intent == "research_company":
            company = entities.get("company") or _extract_after(message, ["research", "about", "find info on"])
            if not company:
                return "Which company should I research? Just say: *research [company name]*"
            await message_status(f"🔍 Researching {company}...")
            result = await research_company(company)
            s = result.get("summary", {})
            if isinstance(s, str):
                return truncate(s)
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

        # ── DRAFT OUTREACH ────────────────────────────────────────────────────
        elif intent == "draft_outreach":
            contact_name = entities.get("person") or entities.get("contact")
            company_name = entities.get("company")
            draft = await draft_email(contact_name=contact_name, company_name=company_name, custom_context=message)
            lines = [
                f"*Draft Email*",
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
                "Reply *send* to send, or give me feedback to revise."
            ]
            return truncate("\n".join(lines))

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
            return truncate("\n".join(lines))

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
            return truncate("\n".join(lines))

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

        # ── GENERAL CHAT ──────────────────────────────────────────────────────
        else:
            context = await build_context(message, intent, entities)
            messages = [
                {"role": "system", "content": f"""You are the personal AI operating system for {config.my_name}, {config.my_role} at {config.company_name}.
{config.company_name}: {config.my_one_liner}
You have full context of their business, contacts, and outreach. Be direct, smart, and immediately useful.
Use Telegram markdown formatting (* for bold, _ for italic).

{f"CONTEXT FROM MEMORY:{chr(10)}{context}" if context else ""}"""},
                {"role": "user", "content": message}
            ]
            response = await complete(messages, task_type="general")
            vec_add("conversations", response, metadata={"role": "assistant"})
            return truncate(response)

    except Exception as e:
        import traceback
        print(f"[Orchestrator Error] {e}\n{traceback.format_exc()}")
        return f"⚠️ Something went wrong: {str(e)[:200]}\n\nTry rephrasing or check the logs."

# Helpers
def _extract_after(text: str, keywords: list) -> str:
    text_lower = text.lower()
    for kw in keywords:
        idx = text_lower.find(kw)
        if idx != -1:
            return text[idx + len(kw):].strip()
    return ""

async def message_status(text: str):
    """Placeholder — bot handlers will send typing indicator instead."""
    print(f"[Status] {text}")

import re
from llm.router import complete

INTENTS = [
    "research_company", "find_contacts", "draft_outreach", "send_email",
    "add_contact", "update_contact", "get_followups", "pipeline_status",
    "save_note", "search_memory", "add_task", "get_tasks", "daily_report", "general_chat"
]

async def classify_intent(message: str) -> dict:
    """Use LLM to classify the intent of a message and extract entities."""

    # Fast rule-based pre-classification for common patterns
    m = message.lower()
    if m.startswith("note:") or m.startswith("remember"):
        return {"intent": "save_note", "entities": {"content": message}, "confidence": 0.95}
    if m.startswith("todo:") or m.startswith("task:") or m.startswith("remind me"):
        return {"intent": "add_task", "entities": {"title": message.replace("todo:", "").replace("task:", "").strip()}, "confidence": 0.95}
    # Confirming a send of the last drafted email.
    _send_phrases = ("send", "send it", "send the email", "send email", "send mail",
                     "send now", "yes send", "send this", "go ahead and send", "fire it")
    if m.strip().strip("!.") in _send_phrases or m.startswith("send to ") or m.startswith("send it to "):
        return {"intent": "send_email", "entities": {}, "confidence": 0.95, "raw_message": message}
    if "daily report" in m or "briefing" in m or "my status" in m:
        return {"intent": "daily_report", "entities": {}, "confidence": 0.95}
    if "follow-up" in m or "followup" in m or "follow up" in m:
        return {"intent": "get_followups", "entities": {}, "confidence": 0.9}
    if "pipeline" in m or "how is outreach" in m:
        return {"intent": "pipeline_status", "entities": {}, "confidence": 0.9}
    # Lead generation: find people/emails/phone numbers to contact.
    _lead_triggers = (
        "find contact", "find me contact", "find contacts", "get me contact",
        "find lead", "find leads", "get leads", "get me leads", "generate lead",
        "decision maker", "contact details", "contact info", "contact number",
        "phone number", "email of", "emails of", "their email", "reach out to",
    )
    if any(t in m for t in _lead_triggers):
        return {"intent": "find_contacts", "entities": {}, "confidence": 0.9, "raw_message": message}

    # LLM classification for everything else
    messages = [
        {"role": "system", "content": f"""You are an intent classifier for a founder's operating system.
Classify the user message into one of these intents: {', '.join(INTENTS)}
Extract any relevant entities (company names, person names, email addresses, etc.)
Respond ONLY with JSON like: {{"intent": "...", "entities": {{}}, "confidence": 0.0}}"""},
        {"role": "user", "content": message}
    ]
    raw = await complete(messages, task_type="general", max_tokens=200)
    clean = raw.strip().replace("```json", "").replace("```", "").strip()
    try:
        import json
        result = json.loads(clean)
        result["raw_message"] = message
        return result
    except Exception:
        return {"intent": "general_chat", "entities": {}, "confidence": 0.5, "raw_message": message}

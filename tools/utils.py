import re
from datetime import datetime

URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)

def extract_urls(text: str) -> list:
    """Return a de-duplicated list of http(s) URLs found in text."""
    if not text:
        return []
    seen = []
    for url in URL_RE.findall(text):
        url = url.rstrip(".,;:)]}\u201d\u2019")
        if url not in seen:
            seen.append(url)
    return seen

def format_contact(contact: dict) -> str:
    """Format a contact dict for display in Telegram."""
    lines = [f"*{contact.get('name', 'Unknown')}*"]
    if contact.get("role"):
        lines.append(f"  Role: {contact['role']}")
    if contact.get("company"):
        lines.append(f"  Company: {contact['company']}")
    if contact.get("email"):
        lines.append(f"  Email: {contact['email']}")
    if contact.get("linkedin_url"):
        lines.append(f"  LinkedIn: {contact['linkedin_url']}")
    if contact.get("status"):
        lines.append(f"  Status: {contact['status']}")
    if contact.get("next_followup_at"):
        lines.append(f"  Follow-up: {contact['next_followup_at'][:10]}")
    return "\n".join(lines)

def now_iso() -> str:
    return datetime.now().isoformat()

def truncate(text: str, max_len: int = 3800) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "...\n_(truncated)_"

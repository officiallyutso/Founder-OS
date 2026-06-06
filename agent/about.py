"""Self-description: who built the agent, how it's architected, and what it can do.

Counts are computed live from the tool registry so the description never drifts
from reality as tools are added or self-authored.
"""
from collections import Counter

from agent import registry

BUILDER = "Utso (@officiallyutso)"

ARCHITECTURE = [
    "Agentic core: a ReAct-style tool-calling loop with plan -> execute -> verify (planner + self-critic).",
    "Layered memory: a ChromaDB vector store, a SQLite relational store, a local knowledge graph, and a live Founder World Model.",
    "Hybrid retrieval: dense + sparse (BM25) fused with Reciprocal Rank Fusion, episodic recall, and nightly memory consolidation.",
    "Self-evolution: lessons, reusable skills, a self-editable operating manual, self-authored tools, and an A/B strategy optimizer.",
    "Multi-agent orchestration: a supervisor that delegates to researcher / outreach / ops / analyst specialists, including in parallel.",
    "Perception: speech-to-text for voice notes, image understanding, document parsing + RAG, inbox reading, headless browsing, and topic monitors.",
    "Voice in and out: it transcribes your voice notes and can reply with spoken voice messages.",
    "Safety & control: a non-editable constitution, tiered autonomy, prompt-injection defense, an approval gate, spend caps, and a kill switch.",
    "Observability: per-turn tracing, token/cost tracking, a self-eval harness, and replay.",
    "Smart LLM routing across Groq / Gemini / OpenAI / Ollama with automatic fallback and a semantic cache.",
    "Proactive autonomy: a heartbeat plus scheduled briefings, follow-ups, monitors, memory consolidation, and nightly backups.",
    "Production-ready: Docker deployment, automatic backups, and a pytest regression suite.",
]

CAPABILITIES = [
    "Research companies and people, and find contactable leads",
    "Run a CRM pipeline and schedule follow-ups",
    "Draft (and, with your approval, send) outreach emails; draft LinkedIn / X posts",
    "Set reminders and manage tasks, goals, and durable multi-session projects",
    "Manage your Google Calendar",
    "Generate PDFs, documents, and charts and deliver them to you on Telegram",
    "Ingest your own files and answer questions grounded in them (RAG)",
    "Track cash, burn, and MRR and warn you when runway gets short",
    "Understand your voice notes and reply by voice",
    "Learn your preferences and improve itself over time",
]


def describe() -> dict:
    cats = Counter(t.category for t in registry.all_tools())
    total = len(registry.all_tools())
    return {
        "name": "Founder OS",
        "tagline": "A self-evolving, autonomous AI chief-of-staff — a virtual cofounder.",
        "built_by": BUILDER,
        "complexity": (
            f"Genuinely advanced: {total} tools across {len(cats)} categories and "
            f"{len(ARCHITECTURE)} major subsystems (agentic loop, layered memory, "
            f"self-evolution, multi-agent orchestration, perception, safety, observability)."
        ),
        "total_tools": total,
        "tools_by_category": dict(sorted(cats.items(), key=lambda kv: -kv[1])),
        "architecture": ARCHITECTURE,
        "capabilities": CAPABILITIES,
        "design_note": "Built to run locally and on free tiers wherever possible.",
    }

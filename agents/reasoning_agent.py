"""Agentic reasoning pipeline (self-improving via prompting, not code changes).

A user query passes through several LLM stages to produce the best possible
answer:

  1. PLAN     — analyze the query + context, break it into steps, and decide
                whether fresh web information is needed (and what to search).
  2. GATHER   — if the plan asked for it, run web searches and collect findings.
  3. DRAFT    — produce a first full answer using the plan + context + findings.
  4. CRITIQUE — the model reviews its own draft for gaps, errors, and weak spots.
  5. REFINE   — produce the final, polished, action-oriented answer.

This makes the assistant "think" in multiple passes instead of one shot. It is
intentionally prompt-based — no self-modifying code.
"""
import json
import logging

from llm.router import complete
from tools.web_search import search
from config import config

logger = logging.getLogger(__name__)


def _persona() -> str:
    return (f"You are the personal AI operating system for {config.my_name}, "
            f"{config.my_role} at {config.company_name}. "
            f"{config.company_name}: {config.my_one_liner}. "
            "You are sharp, candid, and relentlessly useful to a startup founder.")


async def _plan(query: str, context: str) -> dict:
    messages = [
        {"role": "system", "content": _persona() + (
            " You are in the PLANNING stage. Think about what a great answer "
            "needs. Decide if you need fresh, external/web information.")},
        {"role": "user", "content": f"""User query:
{query}

Context already available (memory/CRM):
{context or "(none)"}

Produce a short plan as JSON ONLY:
{{
  "steps": ["concise reasoning steps to answer well"],
  "need_web": true/false,
  "web_queries": ["search queries"],
  "key_considerations": ["what would make this answer excellent / what to avoid"]
}}
Set need_web=true only if external/current facts would materially improve the answer."""}
    ]
    raw = await complete(messages, task_type="analysis", max_tokens=500)
    clean = raw.strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(clean)
    except Exception:
        return {"steps": [], "need_web": False, "web_queries": [], "key_considerations": []}


def _gather(plan: dict, max_queries: int = 3) -> str:
    if not plan.get("need_web"):
        return ""
    findings = []
    for q in (plan.get("web_queries") or [])[:max_queries]:
        try:
            for r in search(q, num_results=4):
                findings.append(f"- {r.get('title','')}: {r.get('snippet','')} ({r.get('url','')})")
        except Exception as e:
            logger.debug(f"gather search failed for '{q}': {e}")
    return "\n".join(findings[:12])


async def _draft(query: str, context: str, plan: dict, findings: str) -> str:
    messages = [
        {"role": "system", "content": _persona() + (
            " You are in the DRAFTING stage. Write a complete, well-structured "
            "answer. Use Telegram markdown (* bold, _ italic). Do not artificially "
            "shorten — be as long as the answer genuinely needs.")},
        {"role": "user", "content": f"""User query:
{query}

Plan / steps:
{json.dumps(plan.get('steps', []), indent=2)}

Things that make this answer excellent:
{json.dumps(plan.get('key_considerations', []), indent=2)}

Context from memory/CRM:
{context or "(none)"}

Fresh web findings:
{findings or "(none)"}

Write the best possible answer now."""}
    ]
    return await complete(messages, task_type="general", max_tokens=2048)


async def _critique(query: str, draft: str) -> str:
    messages = [
        {"role": "system", "content": _persona() + (
            " You are in the CRITIQUE stage. Be a tough reviewer of the draft "
            "below. Find anything missing, vague, generic, wrong, or not "
            "actionable for a founder. Be specific and brief.")},
        {"role": "user", "content": f"""Original query:
{query}

Draft answer:
{draft}

List the concrete improvements that would make this answer noticeably better.
If it is already excellent, say so briefly."""}
    ]
    return await complete(messages, task_type="analysis", max_tokens=500)


async def _refine(query: str, draft: str, critique: str) -> str:
    messages = [
        {"role": "system", "content": _persona() + (
            " You are in the FINAL stage. Rewrite the draft into the best final "
            "answer, applying the critique. Use Telegram markdown (* bold, _ "
            "italic). Be direct and useful. Output only the final answer.")},
        {"role": "user", "content": f"""Original query:
{query}

Draft:
{draft}

Critique to apply:
{critique}

Write the final, improved answer."""}
    ]
    return await complete(messages, task_type="general", max_tokens=2048)


async def deep_reason(query: str, context: str = "", allow_web: bool = True) -> str:
    """Run the full multi-step reasoning pipeline and return the final answer."""
    try:
        plan = await _plan(query, context)
        findings = _gather(plan) if allow_web else ""
        draft = await _draft(query, context, plan, findings)
        critique = await _critique(query, draft)
        final = await _refine(query, draft, critique)
        return final
    except Exception as e:
        logger.error(f"deep_reason failed ({e}); falling back to single-pass answer.")
        messages = [
            {"role": "system", "content": _persona() + " Use Telegram markdown."},
            {"role": "user", "content": f"{query}\n\nContext:\n{context}"},
        ]
        return await complete(messages, task_type="general")

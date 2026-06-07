"""Confidence & abstention.

Two layers keep the agent honest:
  - A calibration directive in the system prompt (see identity.py) tells it to
    abstain and ask rather than guess on every turn (free, broad).
  - This module surfaces a *measured* confidence signal: the critic returns a
    confidence level + an optional clarifying question, and we annotate genuinely
    low-confidence answers so the founder is never handed a confident-sounding
    guess. Helpers are pure so they're easy to test.
"""
import re

_UNCERTAIN_HINTS = (
    "i'm not sure", "i am not sure", "not certain", "i don't know", "i do not know",
    "unsure", "can't confirm", "cannot confirm", "might be", "may be wrong",
    "low confidence", "to confirm", "i'm not certain", "no data", "couldn't find",
    "could not find", "don't have", "do not have",
)


def expresses_uncertainty(text: str) -> bool:
    t = (text or "").lower()
    return any(h in t for h in _UNCERTAIN_HINTS)


def annotate(final_text: str, confidence: str, clarify: str = "") -> str:
    """Append an honest low-confidence note (+ a clarifying question) when warranted.

    No-ops when confidence isn't low or the answer already hedges, so high-quality
    answers stay clean.
    """
    if not final_text:
        return final_text
    if (confidence or "").lower() != "low":
        return final_text
    if expresses_uncertainty(final_text):
        return final_text
    note = "\n\n_Low confidence — I may be missing context here, so please double-check."
    clarify = (clarify or "").strip()
    if clarify:
        if not clarify.endswith("?"):
            clarify += "?"
        note += f" To pin it down: {clarify}"
    note += "_"
    return final_text + note

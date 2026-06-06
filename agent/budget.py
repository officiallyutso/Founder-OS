"""Spend caps, usage counting, and kill switch.

A simple daily LLM-call budget (free to run, protects against runaway loops and
surprise API bills) plus a global pause switch. Counting is centralized so both
the tool-calling client and the plain completion router report into it.
"""
import logging

from agent import store
from config import config

logger = logging.getLogger(__name__)


class BudgetError(Exception):
    pass


def check_before_call():
    """Raise BudgetError if paused or over the daily cap."""
    if config.agent_paused:
        raise BudgetError("Agent is paused (AGENT_PAUSED=true). No model calls allowed.")
    cap = config.daily_llm_call_cap or 0
    if cap > 0:
        used = store.usage_today().get("llm_calls", 0)
        if used >= cap:
            raise BudgetError(f"Daily LLM call cap reached ({used}/{cap}). Resets tomorrow "
                              f"or raise DAILY_LLM_CALL_CAP.")


def note_call():
    try:
        store.incr_usage(llm=1)
    except Exception:
        pass


def status() -> dict:
    u = store.usage_today()
    cap = config.daily_llm_call_cap or 0
    return {
        "day": u.get("day"),
        "llm_calls": u.get("llm_calls", 0),
        "cap": cap or "unlimited",
        "paused": config.agent_paused,
        "autonomy_level": config.autonomy_level,
    }

"""Tool-calling completion layer.

The agentic loop needs native function/tool calling. Both Groq (llama-3.3-70b)
and OpenAI (gpt-4o-mini) speak the OpenAI tool-calling format, so we try them in
order and fall back on error/rate-limit. Returns a normalized assistant turn.

Normalized return shape:
    {
        "content": str | None,
        "tool_calls": [ {"id": str, "name": str, "arguments": dict} ],
        "provider": str,
        "raw": <assistant message dict to append back into the transcript>,
    }
"""
import json
import logging

from config import config

logger = logging.getLogger(__name__)

# Lazy singletons.
_groq = None
_openai = None
_ollama = None


def _get_groq():
    global _groq
    if _groq is None and config.groq_api_key:
        from groq import AsyncGroq
        _groq = AsyncGroq(api_key=config.groq_api_key)
    return _groq


def _get_openai():
    global _openai
    if _openai is None and config.openai_api_key:
        from openai import AsyncOpenAI
        _openai = AsyncOpenAI(api_key=config.openai_api_key)
    return _openai


def _get_ollama():
    global _ollama
    if _ollama is None and config.ollama_enabled:
        from openai import AsyncOpenAI
        _ollama = AsyncOpenAI(base_url=config.ollama_base_url, api_key="ollama")
    return _ollama


# Provider chain for tool calling: (name, client_getter, model).
def _chain():
    chain = []
    if config.groq_api_key:
        chain.append(("groq", _get_groq, "llama-3.3-70b-versatile"))
    if config.openai_api_key:
        chain.append(("openai", _get_openai, "gpt-4o-mini"))
    if config.ollama_enabled:
        # Local fallback for tool calling (model must support tools, e.g. llama3.1).
        chain.append(("ollama", _get_ollama, config.ollama_model))
    return chain


def _normalize(provider: str, msg) -> dict:
    """Convert a provider assistant message into the normalized shape."""
    tool_calls = []
    raw_tool_calls = []
    for tc in (getattr(msg, "tool_calls", None) or []):
        try:
            args = json.loads(tc.function.arguments or "{}")
        except Exception:
            args = {}
        tool_calls.append({"id": tc.id, "name": tc.function.name, "arguments": args})
        raw_tool_calls.append({
            "id": tc.id,
            "type": "function",
            "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
        })

    raw = {"role": "assistant", "content": msg.content or ""}
    if raw_tool_calls:
        raw["tool_calls"] = raw_tool_calls

    return {
        "content": msg.content,
        "tool_calls": tool_calls,
        "provider": provider,
        "raw": raw,
    }


async def complete_with_tools(messages: list, tools: list, max_tokens: int = 1500,
                              temperature: float = 0.4) -> dict:
    """Run one tool-calling completion, falling back across providers."""
    chain = _chain()
    if not chain:
        raise RuntimeError("No tool-calling provider configured (need GROQ_API_KEY or OPENAI_API_KEY).")

    from agent import budget
    budget.check_before_call()  # raises BudgetError if paused / over cap
    budget.note_call()

    last_error = None
    for provider, getter, model in chain:
        client = getter()
        if client is None:
            continue
        try:
            kwargs = dict(model=model, messages=messages, max_tokens=max_tokens,
                          temperature=temperature)
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            resp = await client.chat.completions.create(**kwargs)
            try:
                usage = getattr(resp, "usage", None)
                if usage:
                    from agent import budget, trace
                    budget.note_tokens(model, getattr(usage, "prompt_tokens", 0) or 0,
                                       getattr(usage, "completion_tokens", 0) or 0)
                    trace.add("llm", {"provider": provider, "model": model,
                                      "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                                      "completion_tokens": getattr(usage, "completion_tokens", 0)})
            except Exception:
                pass
            return _normalize(provider, resp.choices[0].message)
        except Exception as e:
            logger.warning(f"[tool_client] {provider} failed: {e}; trying next.")
            last_error = e
            continue

    raise Exception(f"All tool-calling providers failed. Last error: {last_error}")

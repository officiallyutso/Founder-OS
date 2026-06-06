"""Local LLM via Ollama (OpenAI-compatible endpoint).

Free, private, offline fallback. When OLLAMA_ENABLED=true and an Ollama server is
running locally, this becomes a resilient last-resort provider in the routing chain
(and a privacy option). Uses the OpenAI client pointed at the Ollama base URL.

Setup:  install Ollama, then `ollama pull llama3.1`, then set OLLAMA_ENABLED=true.
"""
import logging

from config import config

logger = logging.getLogger(__name__)

_client = None


def is_enabled() -> bool:
    return bool(config.ollama_enabled)


def _get_client():
    global _client
    if _client is None:
        from openai import AsyncOpenAI
        # Ollama ignores the api key but the SDK requires a non-empty string.
        _client = AsyncOpenAI(base_url=config.ollama_base_url, api_key="ollama")
    return _client


async def complete(messages: list, max_tokens: int = 2048) -> str:
    if not is_enabled():
        raise RuntimeError("Ollama not enabled (set OLLAMA_ENABLED=true).")
    client = _get_client()
    resp = await client.chat.completions.create(
        model=config.ollama_model,
        messages=messages,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content

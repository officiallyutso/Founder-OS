import logging
from llm import groq_client, gemini_client, openai_client, ollama_client, cache
from llm.groq_client import RateLimitError
from config import config

logger = logging.getLogger(__name__)

# Task type → preferred model chain
ROUTING = {
    "general":   ["groq", "gemini", "openai"],
    "research":  ["gemini", "groq", "openai"],
    "outreach":  ["groq", "gemini", "openai"],
    "analysis":  ["gemini", "groq", "openai"],
}

CLIENTS = {
    "groq":   groq_client.complete,
    "gemini": gemini_client.complete,
    "openai": openai_client.complete,
    "ollama": ollama_client.complete,
}


def _chain_for(task_type: str) -> list:
    chain = list(ROUTING.get(task_type, ROUTING["general"]))
    # Local model is appended as a free, offline last resort when enabled.
    if config.ollama_enabled and "ollama" not in chain:
        chain.append("ollama")
    return chain


async def complete(messages: list, task_type: str = "general", max_tokens: int = 2048) -> str:
    # Semantic cache first — avoid a paid call for near-duplicate prompts.
    cached = cache.get(messages, task_type)
    if cached is not None:
        return cached

    from agent import budget
    budget.check_before_call()  # raises BudgetError if paused / over cap
    budget.note_call()

    chain = _chain_for(task_type)
    last_error = None

    for model_name in chain:
        try:
            logger.info(f"LLM call: model={model_name}, task={task_type}")
            result = await CLIENTS[model_name](messages, max_tokens=max_tokens)
            logger.info(f"LLM success: model={model_name}")
            cache.put(messages, task_type, result)
            return result
        except RateLimitError as e:
            logger.warning(f"Rate limit on {model_name}, trying next. Error: {e}")
            last_error = e
            continue
        except Exception as e:
            logger.error(f"Error on {model_name}: {e}, trying next.")
            last_error = e
            continue

    raise Exception(f"All LLM providers failed. Last error: {last_error}")

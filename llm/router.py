import logging
from llm import groq_client, gemini_client, openai_client
from llm.groq_client import RateLimitError

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
}

async def complete(messages: list, task_type: str = "general", max_tokens: int = 2048) -> str:
    from agent import budget
    budget.check_before_call()  # raises BudgetError if paused / over cap
    budget.note_call()

    chain = ROUTING.get(task_type, ROUTING["general"])
    last_error = None

    for model_name in chain:
        try:
            logger.info(f"LLM call: model={model_name}, task={task_type}")
            result = await CLIENTS[model_name](messages, max_tokens=max_tokens)
            logger.info(f"LLM success: model={model_name}")
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

import google.generativeai as genai
from config import config

if config.gemini_api_key:
    genai.configure(api_key=config.gemini_api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
else:
    model = None

async def complete(messages: list, max_tokens: int = 2048) -> str:
    if model is None:
        raise RuntimeError("Gemini not configured (GOOGLE_GEMINI_API_KEY missing)")
    # Convert OpenAI-style messages to Gemini format
    prompt_parts = []
    for m in messages:
        role = m["role"]
        content = m["content"]
        if role == "system":
            prompt_parts.append(f"[System Instructions]\n{content}\n")
        elif role == "user":
            prompt_parts.append(f"User: {content}")
        elif role == "assistant":
            prompt_parts.append(f"Assistant: {content}")
    prompt = "\n".join(prompt_parts)

    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(max_output_tokens=max_tokens),
        )
        return response.text
    except Exception:
        raise

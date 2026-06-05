"""Vision layer: turn an image into a rich textual understanding.

Primary: OpenAI gpt-4o-mini (vision capable). Fallback: Gemini 1.5 Flash.
Whichever provider is configured is used; if none support vision, a graceful
message is returned so the rest of the pipeline keeps working.
"""
import base64
import logging

from config import config

logger = logging.getLogger(__name__)

DEFAULT_PROMPT = (
    "You are analyzing an image sent to a startup founder's operating system. "
    "Describe what the image shows in detail. If it contains text (a screenshot, "
    "slide, whiteboard, business card, document, chart, or article), transcribe "
    "the key text and data accurately. Extract any company names, people, roles, "
    "emails, phone numbers, metrics, or action items. Be thorough and factual."
)

try:
    from openai import AsyncOpenAI
    _openai = AsyncOpenAI(api_key=config.openai_api_key) if config.openai_api_key else None
except Exception:  # pragma: no cover - import guard
    _openai = None

try:
    import google.generativeai as genai
    if config.gemini_api_key:
        genai.configure(api_key=config.gemini_api_key)
        _gemini = genai.GenerativeModel("gemini-1.5-flash")
    else:
        _gemini = None
except Exception:  # pragma: no cover - import guard
    _gemini = None


async def describe_image(image_bytes: bytes, caption: str = "", mime: str = "image/jpeg") -> str:
    """Return a detailed textual understanding of an image."""
    prompt = DEFAULT_PROMPT
    if caption:
        prompt += f"\n\nThe sender added this caption/context: {caption}"

    # ── Primary: OpenAI vision ────────────────────────────────────────────────
    if _openai is not None:
        try:
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            resp = await _openai.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                        ],
                    }
                ],
            )
            return resp.choices[0].message.content
        except Exception as e:
            logger.error(f"OpenAI vision failed: {e}, trying Gemini fallback.")

    # ── Fallback: Gemini vision ───────────────────────────────────────────────
    if _gemini is not None:
        try:
            resp = _gemini.generate_content([prompt, {"mime_type": mime, "data": image_bytes}])
            return resp.text
        except Exception as e:
            logger.error(f"Gemini vision failed: {e}")

    return "[Image received, but no vision-capable LLM is configured. Add OPENAI_API_KEY or GOOGLE_GEMINI_API_KEY to read images.]"

"""Text-to-speech for spoken replies (optional, free, no API key).

Uses gTTS (Google Translate TTS) which returns an MP3. Imported lazily — if gTTS
isn't installed the bot just replies in text. Needs internet at runtime.

Setup:  pip install gTTS
"""
import logging

logger = logging.getLogger(__name__)

MAX_TTS_CHARS = 800  # keep clips short/snappy and avoid huge uploads


def available() -> bool:
    try:
        import gtts  # noqa: F401
        return True
    except Exception:
        return False


def synthesize(text: str, out_path: str, lang: str = "en") -> bool:
    """Render text to an MP3 at out_path. Returns True on success."""
    if not available():
        return False
    snippet = (text or "").strip()
    if not snippet:
        return False
    try:
        from gtts import gTTS
        gTTS(text=snippet[:MAX_TTS_CHARS], lang=lang).save(out_path)
        return True
    except Exception as e:
        logger.error(f"[tts] synthesis failed: {e}")
        return False

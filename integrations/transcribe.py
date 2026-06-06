"""Local voice transcription via faster-whisper (optional, offline, free).

Used to turn Telegram voice notes into text the agent can act on. faster-whisper
is imported lazily and the model is cached after first load. If it's not
installed, callers fall back to asking the founder to type.

Setup:  pip install faster-whisper
"""
import logging

logger = logging.getLogger(__name__)

_model = None
_MODEL_SIZE = "base"  # good speed/quality tradeoff on CPU


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(_MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def transcribe_file(path: str) -> str:
    """Transcribe an audio file to text. Returns '' if unavailable/failed."""
    if not available():
        return ""
    try:
        model = _get_model()
        segments, _info = model.transcribe(path, beam_size=1)
        return " ".join(seg.text.strip() for seg in segments).strip()
    except Exception as e:
        logger.error(f"[transcribe] failed: {e}")
        return ""

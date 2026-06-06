"""Voice output tool: let the agent send a spoken Telegram voice message on request.

Without this, when the founder asks for "a voice note / audio / say it out loud",
the model has no way to produce speech and improvises with a text document. This
tool synthesizes speech (gTTS) and delivers it as a real Telegram voice message.
"""
import os
import tempfile

from agent.registry import register


@register(
    name="send_voice_note",
    description="Speak a message aloud and send it to the founder as a Telegram VOICE message. "
                "Use whenever the founder asks for a voice note / audio / for you to 'say', 'tell' "
                "or 'read' something out loud. Keep it concise (a few sentences) — long text is "
                "truncated. This sends audio directly; do NOT use create_document/generate_pdf for "
                "voice requests.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "What to say aloud."},
            "lang": {"type": "string", "description": "Language code (default 'en')."},
        },
        "required": ["text"],
    },
    category="tasks",
)
async def send_voice_note(text, lang="en"):
    from integrations import tts
    if not tts.available():
        return {"spoken": False, "error": "Voice synthesis unavailable (install gTTS)."}
    if not (text or "").strip():
        return {"spoken": False, "error": "Nothing to say (empty text)."}

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as af:
            tmp_path = af.name
        if not tts.synthesize(text, tmp_path, lang=lang or "en"):
            return {"spoken": False, "error": "TTS synthesis failed."}
        from scheduler.jobs import send_voice_to_user
        delivered = await send_voice_to_user(tmp_path)
        return {"spoken": delivered, "delivered": delivered,
                "note": "Voice message sent." if delivered else "Synthesized but bot not available to send."}
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

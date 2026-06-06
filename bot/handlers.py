import logging
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    ContextTypes, MessageHandler, CommandHandler, CallbackQueryHandler, filters,
)

from bot.middleware import is_authorized
from bot.formatters import split_long_message
from agent import core, approvals, store
from llm.vision import describe_image

logger = logging.getLogger(__name__)

_APPROVE_RE = re.compile(r"^\s*(approve|reject)\s+#?(\d+)\s*$", re.IGNORECASE)
_CALLBACK_RE = re.compile(r"^(approve|reject):(\d+)$")


def _approval_keyboard(approval_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve:{approval_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject:{approval_id}"),
    ]])


def _pending_ids() -> set:
    return {a["id"] for a in store.list_pending_approvals()}


async def _notify_new_approvals(update: Update, before: set):
    """After a turn, send tappable approve/reject buttons for any new approvals."""
    for appr in store.list_pending_approvals():
        if appr["id"] in before:
            continue
        text = f"🔐 *Approval needed* (id `{appr['id']}`)\n{appr['summary']}"
        for chunk in split_long_message(text):
            try:
                await update.message.reply_text(
                    chunk, parse_mode="Markdown",
                    reply_markup=_approval_keyboard(appr["id"]),
                )
            except Exception:
                try:
                    await update.message.reply_text(
                        chunk, reply_markup=_approval_keyboard(appr["id"]))
                except Exception as e:
                    logger.error(f"approval button send failed: {e}")


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return
    await _send_reply(
        update,
        "🤖 *Founder OS — autonomous agent online.*\n\n"
        "I'm an agentic, self-evolving chief-of-staff. Just talk to me naturally — "
        "I decide which tools to use and chain them to get things done:\n"
        "• Research, lead-gen, CRM, outreach drafting\n"
        "• Reminders (\"remind me to call Asha at 5pm\")\n"
        "• Google Calendar (once connected)\n"
        "• Tasks, goals, daily briefings\n"
        "• Drafting X / LinkedIn posts\n\n"
        "I learn from how you work and improve over time. Risky actions (sending email, "
        "posting) I'll queue for your `approve <id>`.\n\n"
        "Try: `set a goal to book 5 demos this month`, or `remind me in 2 hours to review the deck`.",
    )


async def approvals_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    pending = store.list_pending_approvals()
    if not pending:
        await _send_reply(update, "No pending approvals.")
        return
    for appr in pending:
        text = f"🔐 *Approval* (id `{appr['id']}`)\n{appr['summary']}"
        for chunk in split_long_message(text):
            try:
                await update.message.reply_text(
                    chunk, parse_mode="Markdown",
                    reply_markup=_approval_keyboard(appr["id"]))
            except Exception:
                await update.message.reply_text(
                    chunk, reply_markup=_approval_keyboard(appr["id"]))


async def on_approval_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle taps on the inline ✅ Approve / ❌ Reject buttons."""
    query = update.callback_query
    if query is None:
        return
    if not is_authorized(query.from_user.id):
        await query.answer("Unauthorized.", show_alert=True)
        return
    m = _CALLBACK_RE.match(query.data or "")
    if not m:
        await query.answer()
        return
    action, aid = m.group(1), int(m.group(2))
    await query.answer("Working…")
    reply = await approvals.approve(aid) if action == "approve" else approvals.reject(aid)
    # Replace the buttons with the outcome so it can't be tapped twice.
    try:
        await query.edit_message_text(reply[:4000])
    except Exception:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(reply[:4000])


def _status_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    async def on_status(_text: str):
        try:
            await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        except Exception:
            pass
    return on_status


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        logger.warning(f"Unauthorized access from user_id={update.effective_user.id}")
        return

    user_message = update.message.text or ""
    logger.info(f"Received: {user_message[:80]}")

    # Approval shortcuts handled directly (no LLM needed).
    m = _APPROVE_RE.match(user_message)
    if m:
        action, aid = m.group(1).lower(), int(m.group(2))
        await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        reply = await approvals.approve(aid) if action == "approve" else approvals.reject(aid)
        await _send_reply(update, reply)
        return

    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    before = _pending_ids()
    try:
        response = await core.run(user_message, on_status=_status_callback(update, ctx))
        await _send_reply(update, response)
        await _notify_new_approvals(update, before)
    except Exception as e:
        logger.error(f"Handler error: {e}")
        await update.message.reply_text(f"⚠️ Error: {str(e)[:200]}")


async def handle_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    msg = update.message
    caption = (msg.caption or "").strip()
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    before = _pending_ids()

    try:
        file_id, mime, is_image, filename = None, "image/jpeg", True, ""
        if msg.photo:
            file_id = msg.photo[-1].file_id
        elif msg.document:
            file_id = msg.document.file_id
            mime = msg.document.mime_type or "application/octet-stream"
            filename = msg.document.file_name or ""
            is_image = mime.startswith("image/")

        if not file_id:
            await update.message.reply_text("I couldn't read that attachment.")
            return

        if is_image:
            tg_file = await ctx.bot.get_file(file_id)
            raw = await tg_file.download_as_bytearray()
            description = await describe_image(bytes(raw), caption=caption, mime=mime)
            response = await core.run(caption or "(image attached)", image_context=description,
                                      on_status=_status_callback(update, ctx))
        else:
            # Extract text from PDFs / docx / text docs and feed it to the agent.
            from integrations import documents
            tg_file = await ctx.bot.get_file(file_id)
            raw = await tg_file.download_as_bytearray()
            extracted = documents.extract_text(bytes(raw), mime=mime, filename=filename)
            text = f"The founder shared a document '{filename}'. Caption: {caption or '(none)'}."
            if extracted:
                text += f"\n\n[DOCUMENT CONTENT]\n{extracted}"
            response = await core.run(text, on_status=_status_callback(update, ctx))

        await _send_reply(update, response)
        await _notify_new_approvals(update, before)
    except Exception as e:
        logger.error(f"Media handler error: {e}")
        await update.message.reply_text(f"⚠️ Couldn't process that attachment: {str(e)[:200]}")


async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Transcribe a voice note locally, then run it through the agent."""
    if not is_authorized(update.effective_user.id):
        return
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    msg = update.message
    media = msg.voice or msg.audio
    if not media:
        return
    try:
        from integrations import transcribe
        if not transcribe.available():
            await update.message.reply_text(
                "🎙 Voice transcription isn't installed. Run `pip install faster-whisper` "
                "(and have ffmpeg available), or just type your message.")
            return

        import tempfile, os
        tg_file = await ctx.bot.get_file(media.file_id)
        raw = await tg_file.download_as_bytearray()
        suffix = ".ogg" if msg.voice else ".mp3"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
            tf.write(bytes(raw))
            tmp_path = tf.name
        try:
            text = transcribe.transcribe_file(tmp_path)
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

        if not text:
            await update.message.reply_text("I couldn't transcribe that. Mind typing it?")
            return
        await update.message.reply_text(f"🎙 _heard:_ {text[:200]}", parse_mode="Markdown")
        before = _pending_ids()
        response = await core.run(text, on_status=_status_callback(update, ctx))
        await _send_reply(update, response)
        await _notify_new_approvals(update, before)
    except Exception as e:
        logger.error(f"Voice handler error: {e}")
        await update.message.reply_text(f"⚠️ Voice error: {str(e)[:200]}")


async def _send_reply(update: Update, response: str):
    """Send a (possibly long) reply, degrading from Markdown to plain text safely.

    Telegram's legacy Markdown parser rejects unbalanced *, _, `, [ and other
    characters that routinely appear in agent output (JSON, code, errors), which
    surfaces as a 400 Bad Request. We retry the same chunk as plain text, and
    swallow any final send error so a formatting issue never crashes the handler.
    """
    for chunk in split_long_message(response or "(no response)"):
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception:
            try:
                await update.message.reply_text(chunk)
            except Exception as e:
                logger.error(f"reply_text failed: {e}")


def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("approvals", approvals_cmd))
    app.add_handler(CallbackQueryHandler(on_approval_button, pattern=r"^(approve|reject):\d+$"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_media))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_media))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

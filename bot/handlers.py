import logging
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes, MessageHandler, CommandHandler, filters
from bot.middleware import is_authorized
from bot.formatters import split_long_message
from orchestrator.response_builder import process_message
from llm.vision import describe_image

logger = logging.getLogger(__name__)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return
    await update.message.reply_text(
        "👋 *Founder OS online.*\n\n"
        "I'm your personal executive assistant. Try:\n"
        "• `research [company name]`\n"
        "• `draft email to [person] at [company]`\n"
        "• `add [name] from [company] to CRM`\n"
        "• `who do I need to follow up with`\n"
        "• `show pipeline`\n"
        "• `daily report`\n"
        "• `note: [anything]`\n\n"
        "📥 *Just send me anything* — text, a link, or an image. I'll read it, "
        "understand it, classify it (competitor, research, contact, idea…), and "
        "file it into memory automatically.",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        logger.warning(f"Unauthorized access attempt from user_id={update.effective_user.id}")
        return

    user_message = update.message.text
    logger.info(f"Received: {user_message[:80]}")

    # Show typing indicator
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    try:
        response = await process_message(user_message)
        await _send_reply(update, response)
    except Exception as e:
        logger.error(f"Handler error: {e}")
        await update.message.reply_text(f"⚠️ Error: {str(e)[:200]}")

async def handle_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle photos and documents: read images with vision, then ingest."""
    if not is_authorized(update.effective_user.id):
        logger.warning(f"Unauthorized media from user_id={update.effective_user.id}")
        return

    msg = update.message
    caption = (msg.caption or "").strip()
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    try:
        file_id = None
        mime = "image/jpeg"
        is_image = True
        filename = ""

        if msg.photo:
            file_id = msg.photo[-1].file_id  # largest size
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
            logger.info(f"Image received ({len(raw)} bytes), running vision...")
            description = await describe_image(bytes(raw), caption=caption, mime=mime)
            response = await process_message(caption or "(image attached)", image_context=description)
        else:
            # Non-image document: capture what we know so it's still filed.
            text = (f"Received a document '{filename}' (type: {mime}). "
                    f"Caption: {caption or '(none)'}")
            response = await process_message(text)

        await _send_reply(update, response)
    except Exception as e:
        logger.error(f"Media handler error: {e}")
        await update.message.reply_text(f"⚠️ Couldn't process that attachment: {str(e)[:200]}")

async def _send_reply(update: Update, response: str):
    for chunk in split_long_message(response):
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception:
            # If markdown parsing fails, fall back to plain text.
            await update.message.reply_text(chunk)

def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_media))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

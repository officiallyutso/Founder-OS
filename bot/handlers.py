import logging
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes, MessageHandler, CommandHandler, filters
from bot.middleware import is_authorized
from bot.formatters import split_long_message
from orchestrator.response_builder import process_message

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
        "• `note: [anything]`\n"
        "• Or just talk to me naturally.",
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
        chunks = split_long_message(response)
        for chunk in chunks:
            await update.message.reply_text(chunk, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Handler error: {e}")
        await update.message.reply_text(f"⚠️ Error: {str(e)[:200]}")

def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

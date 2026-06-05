import logging
import os
import sys

# Make all output UTF-8 safe so emojis (used throughout the bot) never crash the
# process on a Windows cp1252 console.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from telegram.ext import ApplicationBuilder
from bot.handlers import register_handlers
from scheduler.jobs import start_scheduler
from config import config

os.makedirs("./data/logs", exist_ok=True)
os.makedirs("./data/chroma", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("./data/logs/founder_os.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)

def main():
    logger.info(f"Starting Founder OS for {config.my_name} @ {config.company_name}")

    app = ApplicationBuilder().token(config.telegram_bot_token).build()
    register_handlers(app)
    start_scheduler(app)

    logger.info("Bot is running. Send a message on Telegram to start.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

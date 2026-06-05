import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from agents.report_agent import daily_briefing
from memory.sql_store import get_contacts_needing_followup
from tools.utils import format_contact

logger = logging.getLogger(__name__)

_bot_app = None

def set_bot(app):
    global _bot_app
    _bot_app = app

async def send_to_user(text: str):
    from config import config
    if _bot_app and config.my_telegram_user_id:
        try:
            await _bot_app.bot.send_message(
                chat_id=config.my_telegram_user_id,
                text=text,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Scheduled message send failed: {e}")

async def job_daily_briefing():
    logger.info("[Scheduler] Running daily briefing job")
    try:
        briefing = await daily_briefing()
        await send_to_user(f"☀️ *Good morning!*\n\n{briefing}")
    except Exception as e:
        logger.error(f"Daily briefing job failed: {e}")

async def job_followup_reminder():
    logger.info("[Scheduler] Checking follow-ups")
    try:
        contacts = get_contacts_needing_followup()
        if contacts:
            lines = [f"🔔 *{len(contacts)} follow-up(s) due today:*", ""]
            for c in contacts[:5]:
                lines.append(f"• {c['name']} @ {c.get('company', '?')} (status: {c.get('status', '?')})")
            await send_to_user("\n".join(lines))
    except Exception as e:
        logger.error(f"Follow-up reminder job failed: {e}")

def start_scheduler(app) -> AsyncIOScheduler:
    set_bot(app)
    scheduler = AsyncIOScheduler()

    # Daily briefing at 8:00 AM
    scheduler.add_job(job_daily_briefing, CronTrigger(hour=8, minute=0), id="daily_briefing")

    # Follow-up reminder at 10:00 AM
    scheduler.add_job(job_followup_reminder, CronTrigger(hour=10, minute=0), id="followup_reminder")

    scheduler.start()
    logger.info("[Scheduler] Started. Daily briefing at 08:00, follow-up check at 10:00.")
    return scheduler

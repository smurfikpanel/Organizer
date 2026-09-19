import asyncio
import datetime as dt
import logging

from aiogram import Bot

from app import notion_service

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60


async def reminder_loop(bot: Bot):
    """Раз на хвилину перевіряє Notion на прострочені нагадування і надсилає їх."""
    while True:
        try:
            now = dt.datetime.now()
            due = notion_service.get_due_reminders(now)
            for page in due:
                props = page["properties"]
                title = notion_service._extract_title(props.get("Name", {}))
                chat_id = props.get("ChatId", {}).get("number")
                if chat_id:
                    await bot.send_message(chat_id, f"🔔 Нагадування: {title}")
                notion_service.mark_reminder_sent(page["id"])
        except Exception:
            logger.exception("Помилка у циклі перевірки нагадувань")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

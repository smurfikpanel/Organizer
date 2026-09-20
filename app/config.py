import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_EXPENSES_DB_ID = os.getenv("NOTION_EXPENSES_DB_ID")
NOTION_TASKS_DB_ID = os.getenv("NOTION_TASKS_DB_ID")
NOTION_REMINDERS_DB_ID = os.getenv("NOTION_REMINDERS_DB_ID")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "USD")

# Часовий пояс, за яким бот рахує "зараз", дати й нагадування — незалежно від того,
# де фізично працює сервер (Render, наприклад, працює за UTC). За замовчуванням Київ.
TIMEZONE_NAME = os.getenv("TIMEZONE", "Europe/Kyiv")
TZ = ZoneInfo(TIMEZONE_NAME)

REQUIRED_VARS = {
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "NOTION_TOKEN": NOTION_TOKEN,
    "NOTION_EXPENSES_DB_ID": NOTION_EXPENSES_DB_ID,
    "NOTION_TASKS_DB_ID": NOTION_TASKS_DB_ID,
    "NOTION_REMINDERS_DB_ID": NOTION_REMINDERS_DB_ID,
    "GEMINI_API_KEY": GEMINI_API_KEY,
}


def validate_config():
    missing = [k for k, v in REQUIRED_VARS.items() if not v]
    if missing:
        raise RuntimeError(
            f"Відсутні змінні оточення у .env: {', '.join(missing)}. "
            f"Скопіюй .env.example у .env і заповни їх."
        )

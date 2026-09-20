import asyncio
import datetime as dt
import logging
import os
import tempfile

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
import httpx

from app import config, gemini_service, notion_service
from app.reminder_loop import reminder_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

config.validate_config()

bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Тимчасова пам'ять про "які саме записи маються на увазі", коли знайдено кілька
# однакових збігів під час видалення/редагування. Ключ — chat_id.
PENDING: dict[int, dict] = {}

ORDINAL_WORDS = {
    "1": 0, "перше": 0, "перший": 0, "першу": 0,
    "2": 1, "друге": 1, "другий": 1, "другу": 1,
    "3": 2, "третє": 2, "третій": 2, "третю": 2,
    "4": 3, "четверте": 3, "четвертий": 3,
    "5": 4, "п'яте": 4, "п'ятий": 4,
}
ALL_WORDS = {"всі", "все", "обидва", "обидві", "обоє", "both", "all", "усі"}

# Останній запис (нагадування/задача), про який щойно йшлося в чаті — щоб фрази типу
# "зміни час на 17:05" без назви могли підхопити потрібний запис. Ключ — chat_id.
LAST_ITEM: dict[int, dict] = {}


def _remember_last(chat_id: int, target: str, item_id: str, title: str):
    LAST_ITEM[chat_id] = {"target": target, "id": item_id, "title": title}


def _authorized(message: Message) -> bool:
    if config.ALLOWED_USER_ID and message.from_user.id != config.ALLOWED_USER_ID:
        return False
    return True


def _is_rate_limit(e: httpx.HTTPStatusError) -> bool:
    return e.response.status_code == 429


async def _process_text(message: Message, text: str):
    try:
        result = gemini_service.classify_message(text)
    except httpx.HTTPStatusError as e:
        if _is_rate_limit(e):
            await message.answer(
                "⏳ Вичерпано денний ліміт запитів до Gemini API. "
                "Спробуй ще раз пізніше (ліміт скидається опівночі за тихоокеанським часом), "
                "або підключи платний тариф на aistudio.google.com для вищих лімітів."
            )
        else:
            logger.exception("Помилка звернення до Gemini API")
            await message.answer(f"⚠️ Помилка звернення до Gemini: {e}")
        return
    except httpx.HTTPError as e:
        logger.exception("Помилка мережі при зверненні до Gemini API")
        await message.answer(f"⚠️ Помилка мережі: {e}")
        return

    await _dispatch_result(message, result, text)


async def _dispatch_result(message: Message, result: dict, text: str):
    msg_type = result.get("type")

    if msg_type == "expense":
        e = result.get("expense") or {}
        amount = e.get("amount") or 0
        notion_service.add_expense(
            amount=amount,
            currency=e.get("currency") or config.DEFAULT_CURRENCY,
            category=e.get("category") or "Other",
            account=e.get("account"),
            description=e.get("description") or text,
        )
        await message.answer(
            f"💸 Записав витрату: {e.get('description', text)} — "
            f"{amount} {e.get('currency') or config.DEFAULT_CURRENCY} "
            f"({e.get('category') or 'Other'})"
        )

    elif msg_type == "task":
        t = result.get("task") or {}
        title = t.get("title") or text
        deadline = t.get("deadline")
        page = notion_service.add_task(title=title, deadline=deadline)
        _remember_last(message.chat.id, "task", page["id"], title)
        if deadline:
            await message.answer(f"✅ Додав задачу: **{title}** з терміном на {deadline}.")
        else:
            await message.answer(f"✅ Додав задачу: **{title}**.")

    elif msg_type == "reminder":
        r = result.get("reminder") or {}
        title = r.get("title") or text
        when_str = r.get("datetime")
        advance_days = r.get("advance_days")
        try:
            when = dt.datetime.strptime(when_str, "%Y-%m-%d %H:%M").replace(tzinfo=config.TZ)
        except (ValueError, TypeError):
            await message.answer(
                "Не зміг розпізнати точний час нагадування 🤔 "
                "Спробуй сформулювати конкретніше, наприклад: "
                "«нагадай завтра о 12:00 записатись на стрижку»."
            )
            return

        page = notion_service.add_reminder(title=title, when=when, chat_id=message.chat.id)
        _remember_last(message.chat.id, "reminder", page["id"], title)
        reply_lines = [
            f"⏰ Нагадування встановлено на {when.strftime('%Y-%m-%d')} "
            f"о {when.strftime('%H:%M')} — {title}."
        ]

        if advance_days:
            try:
                advance_when = when - dt.timedelta(days=int(advance_days))
                notion_service.add_reminder(
                    title=f"⏳ Скоро: {title}", when=advance_when, chat_id=message.chat.id
                )
                reply_lines.append(
                    f"➕ Додав ще й завчасне нагадування на {advance_when.strftime('%Y-%m-%d')} "
                    f"о {advance_when.strftime('%H:%M')} (за {advance_days} дн. до події)."
                )
            except (TypeError, ValueError):
                pass

        await message.answer("\n".join(reply_lines))

    elif msg_type == "list":
        l = result.get("list") or {}
        target = l.get("target") or "reminders"
        await _handle_list(message, target, l.get("filter_query"))

    elif msg_type == "delete":
        d = result.get("delete") or {}
        await _handle_delete(message, d.get("target"), d.get("query"), d.get("date_hint"))

    elif msg_type == "edit":
        e = result.get("edit") or {}
        await _handle_edit(message, e)

    else:
        n = result.get("note") or {}
        note_text = n.get("text") or text
        page = notion_service.add_task(title=f"📝 {note_text}", deadline=None)
        _remember_last(message.chat.id, "task", page["id"], f"📝 {note_text}")
        await message.answer(f"📝 Записав як нотатку: {note_text}")


def _fmt_when(when: str | None) -> str:
    if not when:
        return "без дати"
    try:
        d = dt.datetime.fromisoformat(when.replace("Z", "+00:00"))
        return d.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return when


async def _handle_list(message: Message, target: str, filter_query: str | None = None):
    if target == "tasks":
        items = notion_service.list_tasks()
        if not items:
            await message.answer("✅ Активних задач немає.")
            return
        lines = ["📋 Активні задачі:"]
        for title, deadline in items:
            lines.append(f"• {title}" + (f" (до {deadline})" if deadline else ""))
        await message.answer("\n".join(lines))

    elif target == "expenses":
        stats = notion_service.expense_stats(filter_query)
        if stats["mode"] == "filtered":
            if stats["count"] == 0:
                await message.answer(f"Не знайшов витрат за запитом «{filter_query}».")
            else:
                totals_str = ", ".join(f"{amt:.2f} {cur}" for cur, amt in stats["totals"].items())
                await message.answer(
                    f"💰 Витрачено на «{filter_query}»: {totals_str} ({stats['count']} записів)"
                )
        else:
            await message.answer(stats["report"])

    else:
        items = notion_service.list_reminders()
        if not items:
            await message.answer("⏰ Активних нагадувань немає.")
            return
        lines = ["⏰ Активні нагадування:"]
        for title, when in items:
            lines.append(f"• {title} — {_fmt_when(when)}")
        await message.answer("\n".join(lines))


def _find_matches(target: str, query: str, date_hint: str | None):
    if target == "reminder":
        raw = notion_service.find_reminders_by_query(query or "", date_hint)
        return [{"id": m["id"], "title": m["title"], "extra": _fmt_when(m["when"])} for m in raw]
    raw = notion_service.find_tasks_by_query(query or "", date_hint)
    return [
        {"id": m["id"], "title": m["title"], "extra": m["deadline"] or "без дедлайну"} for m in raw
    ]


def _format_matches_list(matches: list) -> str:
    lines = []
    for i, m in enumerate(matches, start=1):
        lines.append(f"{i}. {m['title']} — {m['extra']}")
    return "\n".join(lines)


async def _ask_to_clarify(message: Message, action: str, target: str, matches: list, edit_payload: dict | None):
    PENDING[message.chat.id] = {
        "action": action,
        "target": target,
        "matches": matches,
        "edit_payload": edit_payload,
    }
    verb = "видалити" if action == "delete" else "змінити"
    await message.answer(
        f"Знайшов кілька збігів, який саме {verb}?\n{_format_matches_list(matches)}\n\n"
        f"Відповідай номером (наприклад «1» або «перше»), або напиши «всі», щоб {verb} усі."
    )


async def _apply_delete(message: Message, matches: list):
    for m in matches:
        notion_service.archive_page(m["id"])
    names = ", ".join(m["title"] for m in matches)
    if LAST_ITEM.get(message.chat.id, {}).get("id") in {m["id"] for m in matches}:
        LAST_ITEM.pop(message.chat.id, None)
    await message.answer(f"🗑 Видалив: {names}")


async def _apply_edit(message: Message, target: str, matches: list, e: dict):
    new_title = e.get("new_title")
    if target == "reminder":
        when = None
        new_dt = e.get("new_datetime")
        if new_dt:
            try:
                when = dt.datetime.strptime(new_dt, "%Y-%m-%d %H:%M").replace(tzinfo=config.TZ)
            except ValueError:
                pass
        for m in matches:
            notion_service.update_reminder(m["id"], when=when, title=new_title)
        summary = f" на {when.strftime('%Y-%m-%d %H:%M')}" if when else ""
        names = ", ".join(m["title"] for m in matches)
        await message.answer(f"✏️ Оновив «{names}»{summary}.")
    else:
        deadline = e.get("new_deadline")
        for m in matches:
            notion_service.update_task(m["id"], deadline=deadline, title=new_title)
        summary = f" (термін {deadline})" if deadline else ""
        names = ", ".join(m["title"] for m in matches)
        await message.answer(f"✏️ Оновив «{names}»{summary}.")

    if len(matches) == 1:
        _remember_last(message.chat.id, target, matches[0]["id"], new_title or matches[0]["title"])


async def _handle_delete(message: Message, target: str | None, query: str | None, date_hint: str | None = None):
    target = target or "reminder"

    if not query:
        last = LAST_ITEM.get(message.chat.id)
        if last and last["target"] == target:
            await _apply_delete(message, [last])
            return
        await message.answer(
            "🤔 Не зрозумів, яке саме нагадування/задачу видалити — напиши точнішу назву."
        )
        return

    matches = _find_matches(target, query, date_hint)

    if not matches:
        await message.answer(f"🤔 Не знайшов нічого схожого на «{query}». Спробуй іншими словами.")
        return

    if len(matches) > 1:
        await _ask_to_clarify(message, "delete", target, matches, None)
        return

    await _apply_delete(message, matches)


async def _handle_edit(message: Message, e: dict):
    target = e.get("target") or "reminder"
    query = e.get("query")
    date_hint = e.get("date_hint")

    if not query:
        last = LAST_ITEM.get(message.chat.id)
        if last:
            await _apply_edit(message, last["target"], [last], e)
            return
        await message.answer(
            "🤔 Не зрозумів, яке саме нагадування/задачу змінити — напиши точнішу назву."
        )
        return

    matches = _find_matches(target, query, date_hint)

    if not matches:
        await message.answer(f"🤔 Не знайшов нічого схожого на «{query}». Спробуй іншими словами.")
        return

    if len(matches) > 1:
        await _ask_to_clarify(message, "edit", target, matches, e)
        return

    await _apply_edit(message, target, matches, e)


async def _try_handle_pending_reply(message: Message) -> bool:
    """Якщо очікуємо уточнення (номер/«всі») після знайдених кількох збігів — обробляє
    відповідь тут. Повертає True, якщо це справді була відповідь-уточнення."""
    pending = PENDING.get(message.chat.id)
    if not pending:
        return False

    text_norm = message.text.strip().lower()
    matches = pending["matches"]
    selected = None

    if text_norm in ALL_WORDS:
        selected = matches
    elif text_norm in ORDINAL_WORDS and ORDINAL_WORDS[text_norm] < len(matches):
        selected = [matches[ORDINAL_WORDS[text_norm]]]
    elif text_norm.isdigit() and 1 <= int(text_norm) <= len(matches):
        selected = [matches[int(text_norm) - 1]]

    if selected is None:
        # Не схоже на відповідь-уточнення — скидаємо очікування і обробляємо як звичайне повідомлення
        del PENDING[message.chat.id]
        return False

    del PENDING[message.chat.id]
    if pending["action"] == "delete":
        await _apply_delete(message, selected)
    else:
        await _apply_edit(message, pending["target"], selected, pending["edit_payload"])
    return True


@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Привіт! Пиши текстом або надсилай голосові — розпізнаю чи це витрата, "
        "задача, нагадування, перегляд/видалення/редагування, статистика витрат, чи просто нотатка.\n\n"
        "Команди:\n"
        "/reminders — список активних нагадувань\n"
        "/tasks — список активних задач\n"
        "/report — звіт по витратах за поточний місяць\n"
        "/report 2026-06 — звіт за конкретний місяць\n\n"
        "Приклади фраз:\n"
        "«Купив каву за 120 грн»\n"
        "«Витрати» або «Покажи статистику» — звіт за місяць\n"
        "«Скільки я витратив на колу» — сума по конкретному товару\n"
        "«Нагадай завтра о 12:00 записатись на стрижку»\n"
        "«Постав нагадування на оплату інтернету 10 жовтня, нагадай за день до»\n"
        "«Видали нагадування про оплату інтернету»\n"
        "«Зміни дату нагадування оплата інтернету на 9 жовтня»\n"
        "«Зміни час на 17:05» — підхопить останнє нагадування, про яке йшлося"
    )


@dp.message(Command("reminders"))
async def cmd_reminders(message: Message):
    if not _authorized(message):
        return
    await _handle_list(message, "reminders")


@dp.message(Command("tasks"))
async def cmd_tasks(message: Message):
    if not _authorized(message):
        return
    await _handle_list(message, "tasks")


@dp.message(Command("report"))
async def cmd_report(message: Message):
    if not _authorized(message):
        return
    parts = message.text.split()
    if len(parts) > 1 and "-" in parts[1]:
        year_str, month_str = parts[1].split("-")
        year, month = int(year_str), int(month_str)
    else:
        today = dt.date.today()
        year, month = today.year, today.month

    report = notion_service.monthly_report(year, month)
    await message.answer(report)


@dp.message(F.voice)
async def handle_voice(message: Message):
    if not _authorized(message):
        return

    file_info = await bot.get_file(message.voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name
    await bot.download_file(file_info.file_path, destination=tmp_path)

    try:
        result = gemini_service.transcribe_and_classify(tmp_path)
    except httpx.HTTPStatusError as e:
        os.remove(tmp_path)
        if _is_rate_limit(e):
            await message.answer(
                "⏳ Вичерпано денний ліміт запитів до Gemini API. Спробуй пізніше або текстом."
            )
        else:
            logger.exception("Помилка розпізнавання голосового")
            await message.answer(f"⚠️ Не вдалось розпізнати голосове: {e}")
        return
    except httpx.HTTPError as e:
        os.remove(tmp_path)
        logger.exception("Помилка мережі при розпізнаванні голосового")
        await message.answer(f"⚠️ Помилка мережі: {e}")
        return
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    transcript = result.get("transcript", "")
    if transcript:
        await message.answer(f"📝 Розпізнав: _{transcript}_")
    await _dispatch_result(message, result, transcript or "")


@dp.message(F.text)
async def handle_text(message: Message):
    if not _authorized(message):
        return
    if await _try_handle_pending_reply(message):
        return
    await _process_text(message, message.text)


async def main():
    asyncio.create_task(reminder_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())


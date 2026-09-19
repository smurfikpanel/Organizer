import base64
import json
import datetime as dt

import httpx

from app import config

MODEL = "gemini-3.5-flash-lite"
API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
)

CLASSIFY_PROMPT_TEMPLATE = """Ти — асистент, що розбирає повідомлення користувача українською або
англійською мовою і перетворює його на структурований JSON.

Поточна дата і час: {now}

Категорії витрат, які можна використовувати: Food, Shopping, Fun, Work tools, Transport, Cafe, Other.
Рахунки (якщо не вказано явно — став null): Cash, Card, або назва картки як у тексті.

ПРАВИЛА РОЗПІЗНАВАННЯ ДАТ І ЧАСУ (дуже важливо):
- Українці зазвичай пишуть дати у форматі ДЕНЬ.МІСЯЦЬ або "день місяць" (наприклад "10 жовтня"
  або "10.10" означає 10 жовтня — ДЕНЬ, потім МІСЯЦЬ, а не навпаки).
- Якщо два числа підряд (наприклад "17 05") НЕ супроводжуються назвою місяця, словом "числа",
  "дата" чи явною згадкою іншого дня — і перше число ≤ 23, а друге ≤ 59 — це, ЙМОВІРНІШЕ,
  ЧАС (17 годин 05 хвилин), а не дата. У такому разі постав дату на сьогодні (або на завтра,
  якщо цей час сьогодні вже минув), а часом постав саме ці дві цифри.
  Приклад: "нагадай зайти в клод 17 05" → це нагадування на сьогодні/завтра о 17:05,
  а НЕ на 17 травня.
- Якщо вирахувана дата вже минула у поточному році — постав наступний рік.
- Якщо рік не вказано явно і дата ще не минула цього року — рік поточний.
- "сьогодні", "завтра", "післязавтра", "через N днів", "у понеділок" тощо рахуй відносно
  поточної дати і часу, вказаних вище.
- Якщо час доби не вказаний для нагадування — став розумний час за замовчуванням: 09:00.

Визнач тип повідомлення — один з: "expense", "task", "reminder", "list", "delete", "edit", "note".
- "expense" — користувач витратив гроші.
- "task" — потрібно щось зробити, без конкретного часу нагадування, можливо з дедлайном.
- "reminder" — потрібно нагадати про щось у конкретний момент часу (дата + час).
  Якщо користувач просить додатково нагадати заздалегідь ("нагадай за день до цього",
  "за 3 дні до") — заповни advance_days числом днів заздалегідь (наприклад "за день до" → 1).
  Основна дата/час у полі "datetime" — це дата самої події (наприклад дата оплати),
  а не дата завчасного нагадування — про завчасне подбає код окремо.
- "list" — користувач хоче ПОБАЧИТИ існуючі нагадування/задачі/витрати, або дізнатись
  статистику/суму витрат (наприклад "покажи нагадування", "які в мене задачі",
  "витрати", "expenses", "покажи статистику", "скільки я витратив на каву" —
  все це "list" з target "expenses").
  Якщо запитують суму витрат на конкретну річ/категорію ("скільки я витратив на колу") —
  заповни filter_query цим словом ("кола"). Якщо просто хочуть загальну статистику/звіт —
  filter_query = null.
- "delete" — користувач хоче ВИДАЛИТИ існуюче нагадування або задачу
  (наприклад "видали нагадування про оплату інтернету", "прибери задачу зробити сценарій").
- "edit" — користувач хоче ЗМІНИТИ існуюче нагадування або задачу (дату, час, назву).
  Якщо в цьому й попередніх повідомленнях НЕ згадано явно, яке саме нагадування/задачу
  мають на увазі (наприклад просто "зміни час на 17:05", "перенеси на завтра" без назви) —
  постав query як порожній рядок "" (не вигадуй назву) — код сам здогадається, що йдеться
  про останній згаданий запис.
- "note" — тільки якщо повідомлення дійсно ні до чого з вищезгаданого не підходить.

Якщо є дедлайн, але точного часу нагадати немає (наприклад "до кінця тижня", "до 27 липня") —
це "task", а deadline вирахуй як конкретну дату у форматі YYYY-MM-DD.

Поверни ЛИШЕ валідний JSON без жодного тексту навколо, без markdown-обгортки, за такою схемою:

{{
  "type": "expense" | "task" | "reminder" | "list" | "delete" | "edit" | "note",
  "expense": {{
    "amount": число або null,
    "currency": "USD" | "UAH" | ... | null,
    "category": "Food" | "Shopping" | "Fun" | "Work tools" | "Transport" | "Cafe" | "Other" | null,
    "account": рядок або null,
    "description": короткий опис українською
  }},
  "task": {{
    "title": короткий опис завдання українською,
    "deadline": "YYYY-MM-DD" або null
  }},
  "reminder": {{
    "title": короткий опис нагадування українською (без слів "нагадай" тощо),
    "datetime": "YYYY-MM-DD HH:MM",
    "advance_days": число днів заздалегідь або null
  }},
  "list": {{
    "target": "reminders" | "tasks" | "expenses",
    "filter_query": слово/категорія для підрахунку суми витрат, або null
  }},
  "delete": {{
    "target": "reminder" | "task",
    "query": короткі ключові слова з назви, щоб знайти запис (2-4 слова), або "" якщо
      не згадано явно яку саме назву шукати (тоді буде використано останній згаданий запис),
    "date_hint": "YYYY-MM-DD" або null — якщо користувач згадав конкретну дату запису, щоб
      точніше знайти потрібний серед кількох однакових назв (наприклад "видали те що на 2027 рік")
  }},
  "edit": {{
    "target": "reminder" | "task",
    "query": короткі ключові слова з назви, щоб знайти існуючий запис (2-4 слова), або "" якщо
      не згадано явно яку саме назву шукати (тоді буде використано останній згаданий запис),
    "date_hint": "YYYY-MM-DD" або null — так само, якщо згадана дата для уточнення,
    "new_datetime": "YYYY-MM-DD HH:MM" або null (для reminder),
    "new_deadline": "YYYY-MM-DD" або null (для task),
    "new_title": нова назва рядком або null
  }},
  "note": {{
    "text": текст нотатки
  }}
}}

Заповнюй лише той блок, який відповідає визначеному "type", решта блоків нехай будуть null.

Повідомлення користувача:
\"\"\"{message}\"\"\"
"""

VOICE_PROMPT_TEMPLATE = """Ти отримав аудіофайл з голосовим повідомленням користувача
(українською або англійською мовою).

Спочатку подумки транскрибуй аудіо дослівно. Потім застосуй до транскрибованого тексту
ті самі правила класифікації, що й нижче, і поверни ОДИН JSON, який містить одразу і
транскрипт, і розбір.

""" + CLASSIFY_PROMPT_TEMPLATE.replace(
    'Повідомлення користувача:\n"""{message}"""',
    "(текст візьми з власної транскрипції аудіофайлу)",
).replace(
    '"type": "expense" | "task" | "reminder" | "list" | "delete" | "edit" | "note",',
    '"transcript": дослівна транскрипція аудіо,\n  "type": "expense" | "task" | "reminder" | '
    '"list" | "delete" | "edit" | "note",',
)


def _call_gemini(parts: list) -> str:
    """Прямий HTTP-запит до Gemini REST API (без важкого SDK) — повертає текст відповіді."""
    response = httpx.post(
        API_URL,
        params={"key": config.GEMINI_API_KEY},
        json={"contents": [{"parts": parts}]},
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def classify_message(text: str) -> dict:
    """Надсилає текст у Gemini і повертає розібраний JSON з типом та полями."""
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
    prompt = CLASSIFY_PROMPT_TEMPLATE.format(now=now, message=text)
    raw_text = _call_gemini([{"text": prompt}])
    return _parse_json_response(raw_text, fallback_text=text)


def transcribe_and_classify(file_path: str) -> dict:
    """Один запит до Gemini: транскрибує аудіо і одразу класифікує його. Аудіо передається
    inline (base64, прямо в тілі запиту)."""
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
    prompt = VOICE_PROMPT_TEMPLATE.format(now=now)

    with open(file_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("ascii")

    parts = [
        {"inline_data": {"mime_type": "audio/ogg", "data": audio_b64}},
        {"text": prompt},
    ]
    raw_text = _call_gemini(parts)
    result = _parse_json_response(raw_text, fallback_text=None)
    result.setdefault("transcript", "")
    return result


def _parse_json_response(raw_text: str, fallback_text: str | None) -> dict:
    raw = raw_text.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Фолбек: якщо модель щось напартачила з форматом, повертаємо як нотатку
        return {
            "type": "note",
            "note": {"text": fallback_text or raw},
            "transcript": fallback_text or "",
        }

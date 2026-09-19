# Notion Assistant Bot

Telegram-бот, який слухає твої текстові й голосові повідомлення, розпізнає
чи це витрата, задача, нагадування або нотатка — і записує все у Notion.
Голос розпізнає і аналізує Gemini.

## 1. Створення трьох баз у Notion

Створи в Notion нову сторінку (наприклад, "Асистент") і всередині — три
таблиці (databases) з такими колонками:

### База "Expenses" (Витрати)
| Назва колонки | Тип |
|---|---|
| Name | Title |
| Amount | Number |
| Currency | Select (варіанти: USD, UAH, EUR) |
| Category | Select (варіанти: Food, Shopping, Fun, Work tools, Transport, Cafe, Other) |
| Account | Select (варіанти: Cash, Card — додаси свої назви карток) |
| Date | Date |

### База "Tasks" (Задачі)
| Назва колонки | Тип |
|---|---|
| Name | Title |
| Deadline | Date |
| Status | Select (To do, In progress, Done) |
| Source | Text |

### База "Reminders" (Нагадування)
| Назва колонки | Тип |
|---|---|
| Name | Title |
| DateTime | Date (обов'язково увімкни "Include time" у налаштуваннях колонки) |
| Status | Select (Pending, Sent) |
| ChatId | Number |

## 2. Notion-інтеграція

1. Зайди на https://www.notion.so/my-integrations → "New integration".
2. Дай назву (наприклад "TelegramAssistant"), обери свій workspace, збережи.
3. Скопіюй **Internal Integration Token** — це `NOTION_TOKEN`.
4. Зайди в кожну з трьох баз → кнопка "..." зверху → "Connections" → "Connect to" →
   обери свою інтеграцію "TelegramAssistant". Це треба зробити для всіх трьох баз,
   інакше бот не матиме до них доступу.
5. ID бази беруться з URL сторінки бази: відкрий базу як full page, скопіюй
   32-символьний рядок з посилання, наприклад:
   `https://www.notion.so/myworkspace/1a2b3c4d5e6f...?v=...` → `1a2b3c4d5e6f...`
   це і є `NOTION_EXPENSES_DB_ID` / `NOTION_TASKS_DB_ID` / `NOTION_REMINDERS_DB_ID`.

## 3. Telegram бот

1. Напиши @BotFather в Telegram → `/newbot` → дай ім'я і username.
2. Скопіюй виданий токен — це `TELEGRAM_BOT_TOKEN`.
3. Дізнайся свій Telegram user id через @userinfobot — це `ALLOWED_USER_ID`
   (щоб ботом міг користуватись тільки ти).

## 4. Gemini API ключ

1. Зайди на https://aistudio.google.com/app/apikey
2. Створи ключ (безкоштовний рівень достатній для особистого використання) — це `GEMINI_API_KEY`.

## 5. Локальний запуск

```bash
cd notion-assistant-bot
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# відкрий .env і встав усі ключі з кроків 1-4

python -m app.bot
```

Якщо все налаштовано правильно, бот у Telegram відповість на `/start`.
Спробуй написати: "Купив каву за 120 грн" або надіслати голосове.

## 6. Як це працює зсередини

- Будь-яке повідомлення (текст або розшифрований голос) летить у Gemini з
  промптом-класифікатором (`app/gemini_service.py`), який повертає JSON:
  тип повідомлення + структуровані поля.
- Залежно від типу — запис створюється у відповідній базі Notion
  (`app/notion_service.py`).
- Окремий фоновий цикл (`app/reminder_loop.py`) раз на хвилину опитує базу
  Reminders і надсилає повідомлення, коли час нагадування настав.
- `/report` формує зведення за місяць прямо з бази Expenses — у стилі
  твого прикладу зі скріншота.

## 7B. Деплой БЕЗ GitHub і без картки — FPS.ms

Якщо не хочеш возитись з GitHub/Render — є простіший шлях: **FPS.ms**
(panel.fps.ms) — безкоштовний хостинг спеціально для Telegram-ботів,
без картки, файли завантажуються напряму через веб-панель, бот працює
24/7 у звичному polling-режимі (так само, як ти вже тестував локально).

### Крок 1 — реєстрація і сервер

1. Зайди на https://panel.fps.ms → зареєструйся (пошта, без картки).
2. Створи новий сервер → обери пакет **Telegram Bot** → тип **Python**.

### Крок 2 — завантаж файли

У панелі керування сервером відкрий вкладку **Files** і завантаж туди зі
свого проєкту:
- всю папку `app/` (з файлами `bot.py`, `config.py`, `gemini_service.py`,
  `notion_service.py`, `reminder_loop.py`, `__init__.py`)
- `main.py` (лежить у корені проєкту — це стартовий файл спеціально для FPS.ms)
- `requirements.txt`
- `.env` — файл зі своїми ключами (не `.env.example`, а вже заповнений `.env`)

Не завантажуй `venv` — FPS.ms сам встановить бібліотеки з `requirements.txt`.

### Крок 3 — вкажи стартовий файл

У вкладці **Startup** зміни назву стартового файлу з `app.py` (це значення
за замовчуванням) на **`main.py`** — інакше буде конфлікт назв із папкою
`app/`, де лежить код бота.

### Крок 4 — запусти

Перейди у вкладку **Console** і натисни **Start**. За кілька секунд маєш
побачити лог про те, що бот запущено (`aiogram.dispatcher:Run polling...`).
Напиши боту в Telegram — має відповісти одразу, без затримок і "сну"
(на відміну від Render).

### Оновлення бота в майбутньому

Просто заміни потрібні файли у вкладці **Files** на нові версії і натисни
**Restart** у **Console**.

---

## 7A. Альтернатива — деплой на Render (через GitHub)

Бот для деплою працює у webhook-режимі (`app/webhook_app.py`) — це вже готово,
нічого в коді міняти не треба. Просто потрібно:

### Крок 1 — завантажити код на GitHub

1. Зайди на https://github.com → зареєструйся, якщо ще нема акаунту.
2. Натисни "+" у верхньому правому куті → "New repository".
3. Назви репозиторій, наприклад `notion-assistant-bot`, залиш **Public**, натисни
   "Create repository".
4. На сторінці нового репозиторію натисни "uploading an existing file".
5. Перетягни туди **всі файли й папки** зі свого проєкту (крім `venv` і `.env` —
   їх завантажувати не треба, і завдяки `.gitignore` вони й не мали б туди піти,
   якщо ти користуєшся git; при завантаженні вручну через браузер — просто не вибирай
   ці дві речі).
6. Напиши коментар коміту (наприклад "Initial commit"), натисни "Commit changes".

### Крок 2 — створити акаунт на Render і підключити GitHub

1. Зайди на https://render.com → "Get Started for Free" → зареєструйся через GitHub
   (найпростіше — так одразу підключиться доступ до репозиторію).

### Крок 3 — створити Web Service

1. У Render Dashboard: "New +" → "Web Service".
2. Обери свій репозиторій `notion-assistant-bot` → "Connect".
3. Заповни поля:
   - **Name**: будь-яка назва, наприклад `notion-assistant-bot`
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python -m app.webhook_app`
   - **Instance Type**: Free
4. Розгорни розділ "Advanced" (або знайди "Environment Variables") і додай **усі**
   значення зі свого `.env`, по одному:
   - `TELEGRAM_BOT_TOKEN`
   - `ALLOWED_USER_ID`
   - `NOTION_TOKEN`
   - `NOTION_EXPENSES_DB_ID`
   - `NOTION_TASKS_DB_ID`
   - `NOTION_REMINDERS_DB_ID`
   - `GEMINI_API_KEY`
   - `DEFAULT_CURRENCY` (наприклад `USD`)
5. Натисни "Create Web Service".

Render почне збирати і запускати проєкт (займе кілька хвилин). Коли статус стане
"Live" — бот автоматично встановить собі webhook і буде готовий до роботи
(адресу сервісу Render підставляє сам, нічого додатково вказувати не треба).

### Крок 4 — перевір

Напиши боту в Telegram що-небудь. Якщо довго не писав — перша відповідь може
прийти з затримкою 30-60 секунд (безкоштовний сервіс "прокидається"). Далі,
поки активний, відповідає миттєво.

### Оновлення бота в майбутньому

Якщо захочеш змінити код — онови файли в GitHub-репозиторії (можна знову через
"Upload files" у вебінтерфейсі, або встанови git локально для зручності) —
Render підхопить зміни і перезапустить сервіс автоматично.

### Якщо не хочеш, щоб бот засинав

Безкоштовний тариф Render завжди присипляє сервіс без активності — це обмеження
тарифу, не бота. Якщо колись набридне затримка після "сну" — варіанти: платний
тариф Render (від ~$7/міс), або перехід на Oracle Cloud Free Tier (спитай мене,
підкажу як).

## Можливі наступні покращення
- Кнопки підтвердження перед записом у Notion (раптом Gemini помилиться).
- Синхронізація статусу задач у зворотному напрямку (Notion → Telegram).
- Підтримка кількох валют з автоконвертацією.
- Щоденний авто-звіт о заданій годині.

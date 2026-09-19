import datetime as dt
from collections import defaultdict

from notion_client import Client

from app import config

client = Client(auth=config.NOTION_TOKEN)


def add_expense(amount: float, currency: str, category: str, account: str, description: str):
    properties = {
        "Name": {"title": [{"text": {"content": description or "Витрата"}}]},
        "Amount": {"number": amount},
        "Currency": {"select": {"name": currency or config.DEFAULT_CURRENCY}},
        "Category": {"select": {"name": category or "Other"}},
        "Date": {"date": {"start": dt.date.today().isoformat()}},
    }
    if account:
        properties["Account"] = {"select": {"name": account}}
    return client.pages.create(parent={"database_id": config.NOTION_EXPENSES_DB_ID}, properties=properties)


def add_task(title: str, deadline: str | None):
    properties = {
        "Name": {"title": [{"text": {"content": title}}]},
        "Status": {"select": {"name": "To do"}},
        "Source": {"rich_text": [{"text": {"content": "Telegram bot"}}]},
    }
    if deadline:
        properties["Deadline"] = {"date": {"start": deadline}}
    return client.pages.create(parent={"database_id": config.NOTION_TASKS_DB_ID}, properties=properties)


def add_reminder(title: str, when: dt.datetime, chat_id: int):
    properties = {
        "Name": {"title": [{"text": {"content": title}}]},
        "DateTime": {"date": {"start": when.isoformat()}},
        "Status": {"select": {"name": "Pending"}},
        "ChatId": {"number": chat_id},
    }
    return client.pages.create(parent={"database_id": config.NOTION_REMINDERS_DB_ID}, properties=properties)


def get_due_reminders(now: dt.datetime):
    """Повертає всі нагадування зі статусом Pending, час яких вже настав."""
    results = client.databases.query(
        database_id=config.NOTION_REMINDERS_DB_ID,
        filter={
            "and": [
                {"property": "Status", "select": {"equals": "Pending"}},
                {"property": "DateTime", "date": {"on_or_before": now.isoformat()}},
            ]
        },
    )
    return results.get("results", [])


def mark_reminder_sent(page_id: str):
    client.pages.update(page_id=page_id, properties={"Status": {"select": {"name": "Sent"}}})


def list_reminders(limit: int = 20):
    """Повертає активні (Pending) нагадування, відсортовані за часом."""
    results = client.databases.query(
        database_id=config.NOTION_REMINDERS_DB_ID,
        filter={"property": "Status", "select": {"equals": "Pending"}},
        sorts=[{"property": "DateTime", "direction": "ascending"}],
        page_size=limit,
    ).get("results", [])
    items = []
    for page in results:
        props = page["properties"]
        title = _extract_title(props.get("Name", {}))
        date_prop = props.get("DateTime", {}).get("date")
        when = date_prop["start"] if date_prop else "?"
        items.append((title, when))
    return items


def list_tasks(limit: int = 20):
    """Повертає незавершені задачі (Status != Done), відсортовані за дедлайном."""
    results = client.databases.query(
        database_id=config.NOTION_TASKS_DB_ID,
        filter={"property": "Status", "select": {"does_not_equal": "Done"}},
        page_size=limit,
    ).get("results", [])
    items = []
    for page in results:
        props = page["properties"]
        title = _extract_title(props.get("Name", {}))
        date_prop = props.get("Deadline", {}).get("date")
        deadline = date_prop["start"] if date_prop else None
        items.append((title, deadline))
    # сортуємо: спочатку ті що з дедлайном (за зростанням), потім без дедлайну
    items.sort(key=lambda x: (x[1] is None, x[1] or ""))
    return items


def find_reminders_by_query(query: str, date_hint: str | None = None, limit: int = 10):
    """Шукає нагадування за назвою (contains), опційно звужує за датою (date_hint)."""
    if not query:
        return []
    results = client.databases.query(
        database_id=config.NOTION_REMINDERS_DB_ID,
        filter={"property": "Name", "title": {"contains": query}},
        page_size=limit,
    ).get("results", [])
    items = []
    for page in results:
        props = page["properties"]
        title = _extract_title(props.get("Name", {}))
        date_prop = props.get("DateTime", {}).get("date")
        when = date_prop["start"] if date_prop else None
        items.append({"id": page["id"], "title": title, "when": when})

    if date_hint:
        narrowed = [i for i in items if i["when"] and i["when"].startswith(date_hint)]
        if narrowed:
            items = narrowed

    return items


def find_tasks_by_query(query: str, date_hint: str | None = None, limit: int = 10):
    """Шукає задачі за назвою (contains), опційно звужує за датою дедлайну (date_hint)."""
    if not query:
        return []
    results = client.databases.query(
        database_id=config.NOTION_TASKS_DB_ID,
        filter={"property": "Name", "title": {"contains": query}},
        page_size=limit,
    ).get("results", [])
    items = []
    for page in results:
        props = page["properties"]
        title = _extract_title(props.get("Name", {}))
        date_prop = props.get("Deadline", {}).get("date")
        deadline = date_prop["start"] if date_prop else None
        items.append({"id": page["id"], "title": title, "deadline": deadline})

    if date_hint:
        narrowed = [i for i in items if i["deadline"] and i["deadline"].startswith(date_hint)]
        if narrowed:
            items = narrowed

    return items


def find_pages_by_title(database_id: str, query: str, limit: int = 5):
    """Шукає сторінки, назва яких містить query (без урахування регістру)."""
    if not query:
        return []
    results = client.databases.query(
        database_id=database_id,
        filter={"property": "Name", "title": {"contains": query}},
        page_size=limit,
    ).get("results", [])
    items = []
    for page in results:
        title = _extract_title(page["properties"].get("Name", {}))
        items.append({"id": page["id"], "title": title})
    return items


def archive_page(page_id: str):
    client.pages.update(page_id=page_id, archived=True)


def update_reminder(page_id: str, when: dt.datetime | None = None, title: str | None = None):
    properties = {}
    if when is not None:
        properties["DateTime"] = {"date": {"start": when.isoformat()}}
        properties["Status"] = {"select": {"name": "Pending"}}
    if title is not None:
        properties["Name"] = {"title": [{"text": {"content": title}}]}
    if properties:
        client.pages.update(page_id=page_id, properties=properties)


def update_task(page_id: str, deadline: str | None = None, title: str | None = None):
    properties = {}
    if deadline is not None:
        properties["Deadline"] = {"date": {"start": deadline}}
    if title is not None:
        properties["Name"] = {"title": [{"text": {"content": title}}]}
    if properties:
        client.pages.update(page_id=page_id, properties=properties)


def expense_stats(filter_query: str | None = None) -> dict:
    """Якщо filter_query задано — рахує суму витрат, назва яких його містить.
    Інакше повертає звіт за поточний місяць (як monthly_report)."""
    if filter_query:
        results = client.databases.query(
            database_id=config.NOTION_EXPENSES_DB_ID,
            filter={"property": "Name", "title": {"contains": filter_query}},
        ).get("results", [])
        totals = defaultdict(float)
        count = 0
        for page in results:
            props = page["properties"]
            amount = _extract_number(props.get("Amount", {}))
            currency_prop = props.get("Currency", {}).get("select")
            currency = currency_prop["name"] if currency_prop else config.DEFAULT_CURRENCY
            totals[currency] += amount
            count += 1
        return {"mode": "filtered", "query": filter_query, "count": count, "totals": dict(totals)}

    today = dt.date.today()
    return {"mode": "month", "report": monthly_report(today.year, today.month)}


def _extract_number(prop):
    return prop.get("number") or 0


def _extract_select(prop):
    sel = prop.get("select")
    return sel["name"] if sel else "Other"


def _extract_title(prop):
    arr = prop.get("title", [])
    return arr[0]["plain_text"] if arr else ""


def monthly_report(year: int, month: int) -> str:
    """Формує текстовий звіт по витратах за місяць, у стилі скріну користувача."""
    start = dt.date(year, month, 1).isoformat()
    if month == 12:
        end = dt.date(year + 1, 1, 1).isoformat()
    else:
        end = dt.date(year, month + 1, 1).isoformat()

    results = client.databases.query(
        database_id=config.NOTION_EXPENSES_DB_ID,
        filter={
            "and": [
                {"property": "Date", "date": {"on_or_after": start}},
                {"property": "Date", "date": {"before": end}},
            ]
        },
    ).get("results", [])

    total = 0.0
    by_category = defaultdict(lambda: [0.0, 0])
    by_account = defaultdict(float)

    for page in results:
        props = page["properties"]
        amount = _extract_number(props.get("Amount", {}))
        category = _extract_select(props.get("Category", {}))
        account = props.get("Account", {}).get("select")
        account_name = account["name"] if account else "Cash"

        total += amount
        by_category[category][0] += amount
        by_category[category][1] += 1
        by_account[account_name] += amount

    month_names = [
        "Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень",
        "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень",
    ]
    today = dt.date.today()
    lines = [f"📊 {month_names[month - 1]} {year} (станом на {today.day})", ""]
    lines.append("💰 Витрати: $%.2f" % total)
    for cat, (amt, cnt) in sorted(by_category.items(), key=lambda x: -x[1][0]):
        lines.append(f"  {cat}: ${amt:.2f} ({cnt})")
    lines.append("")
    lines.append("💳 По рахунках:")
    for acc, amt in sorted(by_account.items(), key=lambda x: -x[1]):
        lines.append(f"  {acc}: -${amt:.2f}")

    return "\n".join(lines)

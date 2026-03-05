import csv
import io
import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


def env_or_default(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def env_int_or_default(name, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


DEFAULT_ADMIN_BOT_TOKEN = ""
DEFAULT_ADMIN_ID = None
DEFAULT_ADMIN_USERNAME = ""

DEFAULT_MANAGER_BOT_TOKEN = ""

ADMIN_BOT_TOKEN = env_or_default("TELEGRAM_BOT_TOKEN", DEFAULT_ADMIN_BOT_TOKEN)
ADMIN_USERNAME = env_or_default("TELEGRAM_ADMIN_USERNAME", DEFAULT_ADMIN_USERNAME)

MANAGER_BOT_TOKEN = env_or_default("TELEGRAM_MANAGER_BOT_TOKEN", DEFAULT_MANAGER_BOT_TOKEN)
MANAGER_USERNAME = env_or_default("TELEGRAM_MANAGER_USERNAME", ADMIN_USERNAME)

HOST = env_or_default("HOST", "0.0.0.0")
PORT = to_int(env_or_default("PORT", "8000"), 8000)
DEFER_MINUTES = max(to_int(env_or_default("DEFER_MINUTES", "30"), 30), 5)
REMINDER_MINUTES = max(to_int(env_or_default("REMINDER_MINUTES", "30"), 30), 5)

ADMIN_ID = env_int_or_default("TELEGRAM_ADMIN_ID", DEFAULT_ADMIN_ID)
MANAGER_CHAT_ID = env_int_or_default("TELEGRAM_MANAGER_CHAT_ID", ADMIN_ID)

ACTIVE_STATUSES = {"pending", "deferred"}
TERMINAL_STATUSES = {"registered", "cancelled"}
INTEREST_LABELS = {
    "purchase": "Покупка",
    "installment": "Рассрочка",
    "tradein": "Трейд-ин",
}

state_lock = threading.Lock()
leads = []
next_lead_id = 1
queue_message_id = None
admin_updates_offset = 0


def now_ts():
    return time.time()


def ts_str(ts):
    if not ts:
        return "-"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def tg_request(token, method, payload):
    if not token:
        raise RuntimeError("Telegram token is empty")

    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=40) as response:
        raw = response.read().decode("utf-8")
        result = json.loads(raw)

    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")
    return result["result"]


def tg_request_multipart(token, method, fields, file_field, filename, file_bytes, mime_type):
    if not token:
        raise RuntimeError("Telegram token is empty")

    boundary = f"----TenetBoundary{uuid.uuid4().hex}"
    parts = []

    for key, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        parts.append(str(value).encode("utf-8"))
        parts.append(b"\r\n")

    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(
        (
            f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)

    url = f"https://api.telegram.org/bot{token}/{method}"
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=60) as response:
        raw = response.read().decode("utf-8")
        result = json.loads(raw)

    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")
    return result["result"]


def find_lead(lead_id):
    for lead in leads:
        if lead["id"] == lead_id:
            return lead
    return None


def active_leads():
    return [lead for lead in leads if lead["status"] in ACTIVE_STATUSES]


def registered_leads():
    return [lead for lead in leads if lead["status"] == "registered"]


def queue_position_for(lead_id):
    active = active_leads()
    for idx, lead in enumerate(active, start=1):
        if lead["id"] == lead_id:
            return idx
    return None


def status_label(lead):
    status = lead["status"]
    if status == "pending":
        return "В очереди"
    if status == "deferred":
        if lead["deferred_until_ts"]:
            return f"Отложено до {ts_str(lead['deferred_until_ts'])}"
        return "Отложено"
    if status == "registered":
        return "Клиент зарегистрирован"
    if status == "cancelled":
        return "Отменено"
    return status


def lead_message_text(lead):
    queue_pos = queue_position_for(lead["id"])
    queue_line = f"Позиция в очереди: {queue_pos}" if queue_pos else "Позиция в очереди: -"
    interest_line = (
        INTEREST_LABELS.get(lead["interest_type"], "-")
        if lead["interest_type"]
        else "-"
    )
    manager_line = ts_str(lead["manager_sent_at"])
    assigned_line = lead["assigned_to"] or "-"
    return (
        f"Заявка Tenet #{lead['id']}\n"
        f"ФИО: {lead['full_name']}\n"
        f"Email: {lead['email']}\n"
        f"Телефон: {lead['phone']}\n"
        f"Создано: {ts_str(lead['created_ts'])}\n"
        f"Статус: {status_label(lead)}\n"
        f"Интерес: {interest_line}\n"
        f"Назначено: {assigned_line}\n"
        f"Передано менеджеру: {manager_line}\n"
        f"{queue_line}"
    )


def lead_keyboard(lead):
    if lead["status"] in TERMINAL_STATUSES:
        return []

    lead_id = lead["id"]
    return [
        [{"text": "Клиент зарегистрирован", "callback_data": f"lead:register:{lead_id}"}],
        [
            {"text": "Интерес: покупка", "callback_data": f"lead:interest_purchase:{lead_id}"},
            {"text": "Интерес: рассрочка", "callback_data": f"lead:interest_installment:{lead_id}"},
        ],
        [{"text": "Интерес: трейд-ин", "callback_data": f"lead:interest_tradein:{lead_id}"}],
        [
            {"text": "Назначить мне", "callback_data": f"lead:assign:{lead_id}"},
            {"text": "Позвонить", "callback_data": f"lead:call:{lead_id}"},
        ],
        [
            {"text": f"Отложить {DEFER_MINUTES}м", "callback_data": f"lead:defer:{lead_id}"},
            {"text": "Отменить", "callback_data": f"lead:cancel:{lead_id}"},
        ],
    ]


def queue_summary_text():
    active = active_leads()
    waiting = [lead for lead in leads if lead["status"] == "pending"]
    deferred = [lead for lead in leads if lead["status"] == "deferred"]
    registered = [lead for lead in leads if lead["status"] == "registered"]
    cancelled = [lead for lead in leads if lead["status"] == "cancelled"]
    interested = [lead for lead in leads if lead["interest_type"]]

    lines = [
        "Очередь Tenet",
        f"Активные: {len(active)}",
        f"В очереди: {len(waiting)}",
        f"Отложены: {len(deferred)}",
        f"Зарегистрированы: {len(registered)}",
        f"Отменены: {len(cancelled)}",
        f"С интересом (покупка/рассрочка/трейд-ин): {len(interested)}",
        "",
    ]

    if active:
        lines.append("Текущая активная очередь:")
        for idx, lead in enumerate(active[:20], start=1):
            interest_label = INTEREST_LABELS.get(lead["interest_type"], "-")
            lines.append(f"{idx}. #{lead['id']} {lead['full_name']} | {lead['phone']} | {interest_label}")
    else:
        lines.append("Очередь пуста.")

    return "\n".join(lines)


def refresh_queue_summary():
    global queue_message_id

    if not ADMIN_ID:
        return

    summary = queue_summary_text()

    if queue_message_id:
        try:
            tg_request(
                ADMIN_BOT_TOKEN,
                "editMessageText",
                {
                    "chat_id": ADMIN_ID,
                    "message_id": queue_message_id,
                    "text": summary,
                },
            )
            return
        except Exception:
            queue_message_id = None

    message = tg_request(
        ADMIN_BOT_TOKEN,
        "sendMessage",
        {"chat_id": ADMIN_ID, "text": summary},
    )
    queue_message_id = message["message_id"]


def refresh_lead_message(lead):
    if not lead.get("admin_message_id"):
        return

    payload = {
        "chat_id": ADMIN_ID,
        "message_id": lead["admin_message_id"],
        "text": lead_message_text(lead),
        "reply_markup": {"inline_keyboard": lead_keyboard(lead)},
    }
    tg_request(ADMIN_BOT_TOKEN, "editMessageText", payload)


def send_new_lead_to_admin(lead):
    payload = {
        "chat_id": ADMIN_ID,
        "text": lead_message_text(lead),
        "reply_markup": {"inline_keyboard": lead_keyboard(lead)},
    }
    message = tg_request(ADMIN_BOT_TOKEN, "sendMessage", payload)
    lead["admin_message_id"] = message["message_id"]


def send_text_to_admin(text):
    tg_request(ADMIN_BOT_TOKEN, "sendMessage", {"chat_id": ADMIN_ID, "text": text})


def send_lead_to_manager(lead, interest_code, actor):
    if not MANAGER_BOT_TOKEN or not MANAGER_CHAT_ID:
        raise RuntimeError("Manager bot is not configured")

    interest_label = INTEREST_LABELS.get(interest_code, interest_code)
    actor_name = actor or ADMIN_USERNAME or "admin"
    text = (
        f"Лид для отдела продаж #{lead['id']}\n"
        f"Интерес: {interest_label}\n"
        f"ФИО: {lead['full_name']}\n"
        f"Email: {lead['email']}\n"
        f"Телефон: {lead['phone']}\n"
        f"Источник: сайт Tenet\n"
        f"Отправил: {actor_name}\n"
        f"Время: {ts_str(now_ts())}"
    )
    try:
        tg_request(MANAGER_BOT_TOKEN, "sendMessage", {"chat_id": MANAGER_CHAT_ID, "text": text})
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise RuntimeError("Менеджер не запустил бота ОП. Нужно открыть бота и нажать /start.")
        raise


def create_lead(full_name, email, phone):
    global next_lead_id
    now = now_ts()

    with state_lock:
        lead = {
            "id": next_lead_id,
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "status": "pending",
            "interest_type": None,
            "assigned_to": None,
            "created_ts": now,
            "updated_ts": now,
            "registered_ts": None,
            "cancelled_ts": None,
            "deferred_until_ts": None,
            "manager_sent_at": None,
            "admin_message_id": None,
            "last_reminder_ts": None,
            "reminder_count": 0,
        }
        next_lead_id += 1
        leads.append(lead)

    try:
        send_new_lead_to_admin(lead)
        refresh_queue_summary()
    except Exception:
        with state_lock:
            if lead in leads:
                leads.remove(lead)
        raise
    return lead


def mark_registered(lead_id):
    with state_lock:
        lead = find_lead(lead_id)
        if not lead:
            return None, "not_found"
        if lead["status"] == "registered":
            return lead, "already_registered"
        if lead["status"] == "cancelled":
            return lead, "cancelled"

        lead["status"] = "registered"
        lead["registered_ts"] = now_ts()
        lead["updated_ts"] = now_ts()
        lead["deferred_until_ts"] = None

    refresh_lead_message(lead)
    refresh_queue_summary()
    return lead, "ok"


def mark_cancelled(lead_id):
    with state_lock:
        lead = find_lead(lead_id)
        if not lead:
            return None, "not_found"
        if lead["status"] == "cancelled":
            return lead, "already_cancelled"
        if lead["status"] == "registered":
            return lead, "already_registered"

        lead["status"] = "cancelled"
        lead["cancelled_ts"] = now_ts()
        lead["updated_ts"] = now_ts()
        lead["deferred_until_ts"] = None

    refresh_lead_message(lead)
    refresh_queue_summary()
    return lead, "ok"


def mark_deferred(lead_id):
    with state_lock:
        lead = find_lead(lead_id)
        if not lead:
            return None, "not_found"
        if lead["status"] in TERMINAL_STATUSES:
            return lead, "terminal"

        lead["status"] = "deferred"
        lead["deferred_until_ts"] = now_ts() + DEFER_MINUTES * 60
        lead["updated_ts"] = now_ts()

    refresh_lead_message(lead)
    refresh_queue_summary()
    return lead, "ok"


def assign_lead(lead_id, actor_user):
    with state_lock:
        lead = find_lead(lead_id)
        if not lead:
            return None, "not_found"
        if lead["status"] in TERMINAL_STATUSES:
            return lead, "terminal"

        lead["assigned_to"] = actor_user
        lead["status"] = "pending"
        lead["updated_ts"] = now_ts()

    refresh_lead_message(lead)
    refresh_queue_summary()
    return lead, "ok"


def mark_interest(lead_id, interest_code, actor_user):
    with state_lock:
        lead = find_lead(lead_id)
        if not lead:
            return None, "not_found"
        if lead["status"] in TERMINAL_STATUSES:
            return lead, "terminal"

        lead["interest_type"] = interest_code
        lead["status"] = "pending"
        lead["updated_ts"] = now_ts()
        lead["deferred_until_ts"] = None

    send_lead_to_manager(lead, interest_code, actor_user)

    with state_lock:
        lead["manager_sent_at"] = now_ts()
        lead["updated_ts"] = now_ts()

    refresh_lead_message(lead)
    refresh_queue_summary()
    return lead, "ok"


def answer_callback_query(callback_query_id, text, show_alert=False):
    try:
        tg_request(
            ADMIN_BOT_TOKEN,
            "answerCallbackQuery",
            {
                "callback_query_id": callback_query_id,
                "text": text,
                "show_alert": show_alert,
            },
        )
    except Exception:
        return


def list_lines(title, items, formatter, limit=30):
    lines = [title]
    if not items:
        lines.append("Пусто.")
        return "\n".join(lines)

    for idx, lead in enumerate(items[:limit], start=1):
        lines.append(f"{idx}. {formatter(lead)}")
    if len(items) > limit:
        lines.append(f"... и еще {len(items) - limit}")
    return "\n".join(lines)


def compact_lead(lead):
    interest = INTEREST_LABELS.get(lead["interest_type"], "-")
    return f"#{lead['id']} {lead['full_name']} | {lead['phone']} | {status_label(lead)} | {interest}"


def search_leads(query):
    query = query.lower()
    return [
        lead
        for lead in leads
        if query in lead["full_name"].lower()
        or query in lead["email"].lower()
        or query in lead["phone"].lower()
    ]


def export_leads_csv_bytes():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "full_name",
            "email",
            "phone",
            "status",
            "interest_type",
            "assigned_to",
            "created_at",
            "updated_at",
            "registered_at",
            "cancelled_at",
            "deferred_until",
            "manager_sent_at",
            "reminder_count",
        ]
    )

    for lead in leads:
        writer.writerow(
            [
                lead["id"],
                lead["full_name"],
                lead["email"],
                lead["phone"],
                lead["status"],
                lead["interest_type"] or "",
                lead["assigned_to"] or "",
                ts_str(lead["created_ts"]),
                ts_str(lead["updated_ts"]),
                ts_str(lead["registered_ts"]),
                ts_str(lead["cancelled_ts"]),
                ts_str(lead["deferred_until_ts"]),
                ts_str(lead["manager_sent_at"]),
                lead["reminder_count"],
            ]
        )

    return output.getvalue().encode("utf-8")


def send_csv_to_admin():
    csv_bytes = export_leads_csv_bytes()
    filename = f"tenet_leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    tg_request_multipart(
        ADMIN_BOT_TOKEN,
        "sendDocument",
        {"chat_id": ADMIN_ID, "caption": "Экспорт заявок Tenet"},
        "document",
        filename,
        csv_bytes,
        "text/csv",
    )


def help_text():
    return (
        "Команды бота:\n"
        "/queue - текущая очередь\n"
        "/status - статус очереди\n"
        "/new - последние новые заявки\n"
        "/pending - все активные заявки\n"
        "/done - зарегистрированные заявки\n"
        "/stats - статистика\n"
        "/find <текст> - поиск по ФИО/email/телефону\n"
        "/export - выгрузка CSV"
    )


def process_command(text, chat_id):
    if chat_id != ADMIN_ID:
        return

    command = text.strip()
    lowered = command.lower()

    if lowered in ("/start", "/help"):
        send_text_to_admin(help_text())
        send_text_to_admin(queue_summary_text())
        return

    if lowered in ("/queue", "/status"):
        send_text_to_admin(queue_summary_text())
        return

    if lowered == "/new":
        items = [lead for lead in leads if lead["status"] == "pending"][-10:]
        items.reverse()
        send_text_to_admin(list_lines("Последние новые заявки:", items, compact_lead))
        return

    if lowered == "/pending":
        send_text_to_admin(list_lines("Активные заявки:", active_leads(), compact_lead))
        return

    if lowered == "/done":
        send_text_to_admin(list_lines("Зарегистрированные заявки:", registered_leads(), compact_lead))
        return

    if lowered == "/stats":
        total = len(leads)
        pending = len([lead for lead in leads if lead["status"] == "pending"])
        deferred = len([lead for lead in leads if lead["status"] == "deferred"])
        registered = len([lead for lead in leads if lead["status"] == "registered"])
        cancelled = len([lead for lead in leads if lead["status"] == "cancelled"])
        assigned = len([lead for lead in leads if lead["assigned_to"]])
        manager_sent = len([lead for lead in leads if lead["manager_sent_at"]])
        text_out = (
            "Статистика Tenet:\n"
            f"Всего заявок: {total}\n"
            f"В очереди: {pending}\n"
            f"Отложены: {deferred}\n"
            f"Зарегистрированы: {registered}\n"
            f"Отменены: {cancelled}\n"
            f"Назначено менеджеру: {assigned}\n"
            f"Передано в ОП-бот: {manager_sent}"
        )
        send_text_to_admin(text_out)
        return

    if lowered.startswith("/find"):
        parts = command.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            send_text_to_admin("Использование: /find <ФИО/email/телефон>")
            return
        query = parts[1].strip()
        result = search_leads(query)
        send_text_to_admin(list_lines(f"Результаты поиска: {query}", result, compact_lead))
        return

    if lowered == "/export":
        send_csv_to_admin()
        return


def process_message(message):
    text = (message.get("text") or "").strip()
    if not text.startswith("/"):
        return
    chat_id = message.get("chat", {}).get("id")
    try:
        process_command(text, chat_id)
    except Exception as exc:
        send_text_to_admin(f"Ошибка выполнения команды: {exc}")


def process_callback_query(callback):
    data = callback.get("data", "")
    callback_id = callback.get("id")
    from_user = callback.get("from", {})
    from_id = from_user.get("id")
    username = from_user.get("username")
    actor = f"@{username}" if username else f"id:{from_id}"

    if from_id != ADMIN_ID:
        answer_callback_query(callback_id, "Недостаточно прав", True)
        return

    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "lead" or not parts[2].isdigit():
        answer_callback_query(callback_id, "Неизвестная команда")
        return

    action = parts[1]
    lead_id = int(parts[2])

    try:
        if action == "register":
            _, status = mark_registered(lead_id)
            if status == "ok":
                answer_callback_query(callback_id, "Клиент зарегистрирован")
            elif status == "already_registered":
                answer_callback_query(callback_id, "Уже зарегистрирован")
            elif status == "cancelled":
                answer_callback_query(callback_id, "Заявка уже отменена")
            else:
                answer_callback_query(callback_id, "Заявка не найдена")
            return

        if action == "cancel":
            _, status = mark_cancelled(lead_id)
            if status == "ok":
                answer_callback_query(callback_id, "Заявка отменена")
            elif status == "already_cancelled":
                answer_callback_query(callback_id, "Уже отменена")
            elif status == "already_registered":
                answer_callback_query(callback_id, "Уже зарегистрирована")
            else:
                answer_callback_query(callback_id, "Заявка не найдена")
            return

        if action == "defer":
            _, status = mark_deferred(lead_id)
            if status == "ok":
                answer_callback_query(callback_id, f"Отложено на {DEFER_MINUTES} минут")
            elif status == "terminal":
                answer_callback_query(callback_id, "Нельзя отложить закрытую заявку")
            else:
                answer_callback_query(callback_id, "Заявка не найдена")
            return

        if action == "assign":
            _, status = assign_lead(lead_id, actor)
            if status == "ok":
                answer_callback_query(callback_id, "Заявка назначена")
            elif status == "terminal":
                answer_callback_query(callback_id, "Заявка уже закрыта")
            else:
                answer_callback_query(callback_id, "Заявка не найдена")
            return

        if action == "call":
            with state_lock:
                lead = find_lead(lead_id)
            if not lead:
                answer_callback_query(callback_id, "Заявка не найдена")
                return
            answer_callback_query(callback_id, f"Телефон: {lead['phone']}")
            return

        if action.startswith("interest_"):
            interest_code = action.replace("interest_", "", 1)
            if interest_code not in INTEREST_LABELS:
                answer_callback_query(callback_id, "Неизвестный тип интереса")
                return
            _, status = mark_interest(lead_id, interest_code, actor)
            if status == "ok":
                answer_callback_query(callback_id, "Передано менеджеру ОП")
            elif status == "terminal":
                answer_callback_query(callback_id, "Заявка уже закрыта")
            else:
                answer_callback_query(callback_id, "Заявка не найдена")
            return

        answer_callback_query(callback_id, "Неизвестная команда")
    except Exception as exc:
        answer_callback_query(callback_id, f"Ошибка: {exc}", True)


def poll_admin_bot_updates():
    global admin_updates_offset

    tg_request(ADMIN_BOT_TOKEN, "deleteWebhook", {"drop_pending_updates": False})
    while True:
        try:
            updates = tg_request(
                ADMIN_BOT_TOKEN,
                "getUpdates",
                {
                    "offset": admin_updates_offset,
                    "timeout": 25,
                    "allowed_updates": ["message", "callback_query"],
                },
            )
            for update in updates:
                admin_updates_offset = update["update_id"] + 1
                callback = update.get("callback_query")
                if callback:
                    process_callback_query(callback)
                message = update.get("message")
                if message:
                    process_message(message)
        except Exception:
            time.sleep(3)


def reminder_worker():
    reminder_seconds = REMINDER_MINUTES * 60
    while True:
        due = []
        now = now_ts()
        with state_lock:
            for lead in leads:
                if lead["status"] not in ACTIVE_STATUSES:
                    continue

                if lead["status"] == "deferred" and lead["deferred_until_ts"]:
                    if now < lead["deferred_until_ts"]:
                        continue

                lead_age = now - lead["created_ts"]
                since_last = now - (lead["last_reminder_ts"] or 0)
                if lead_age >= reminder_seconds and since_last >= reminder_seconds:
                    lead["last_reminder_ts"] = now
                    lead["reminder_count"] += 1
                    due.append(lead.copy())

        for lead_snapshot in due:
            try:
                tg_request(
                    ADMIN_BOT_TOKEN,
                    "sendMessage",
                    {
                        "chat_id": ADMIN_ID,
                        "text": f"Напоминание по заявке #{lead_snapshot['id']}\n{lead_message_text(lead_snapshot)}",
                    },
                )
            except Exception:
                continue
        time.sleep(20)


class AppHandler(SimpleHTTPRequestHandler):
    def json_response(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/health":
            self.json_response(
                200,
                {
                    "ok": True,
                    "adminConfigured": bool(ADMIN_BOT_TOKEN and ADMIN_ID),
                    "managerConfigured": bool(MANAGER_BOT_TOKEN and MANAGER_CHAT_ID),
                },
            )
            return
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/leads":
            self.json_response(404, {"ok": False, "error": "Not found"})
            return

        if not ADMIN_BOT_TOKEN or not ADMIN_ID:
            self.json_response(
                500,
                {
                    "ok": False,
                    "error": "Backend not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_ID.",
                },
            )
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body_raw = self.rfile.read(content_length)

        try:
            payload = json.loads(body_raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.json_response(400, {"ok": False, "error": "Invalid JSON"})
            return

        full_name = str(payload.get("fullName", "")).strip()
        email = str(payload.get("email", "")).strip()
        phone = str(payload.get("phone", "")).strip()

        if not full_name or not email or not phone:
            self.json_response(400, {"ok": False, "error": "All fields are required"})
            return

        if "@" not in email or "." not in email:
            self.json_response(400, {"ok": False, "error": "Invalid email"})
            return

        try:
            lead = create_lead(full_name, email, phone)
        except urllib.error.URLError as exc:
            self.json_response(502, {"ok": False, "error": f"Telegram is unavailable: {exc}"})
            return
        except Exception as exc:
            self.json_response(500, {"ok": False, "error": f"Failed to send lead: {exc}"})
            return

        self.json_response(200, {"ok": True, "leadId": lead["id"]})

    def log_message(self, fmt, *args):
        return


def main():
    if not ADMIN_BOT_TOKEN or not ADMIN_ID:
        print("WARN: TELEGRAM_BOT_TOKEN or TELEGRAM_ADMIN_ID is missing.")
    else:
        print(f"Admin: {ADMIN_USERNAME} ({ADMIN_ID})")
        polling_thread = threading.Thread(target=poll_admin_bot_updates, daemon=True)
        polling_thread.start()
        reminder_thread = threading.Thread(target=reminder_worker, daemon=True)
        reminder_thread.start()

    if MANAGER_BOT_TOKEN and MANAGER_CHAT_ID:
        print(f"Manager target: {MANAGER_USERNAME} ({MANAGER_CHAT_ID})")
    else:
        print("WARN: manager bot is not configured.")

    handler = partial(AppHandler, directory=os.getcwd())
    server = ThreadingHTTPServer((HOST, PORT), handler)
    print(f"Serving on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()

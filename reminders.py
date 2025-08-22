# reminders.py — модуль напоминаний (разовые и регулярные) для aiogram v3 в стиле calc.py
import asyncio
import json
import calendar
from pathlib import Path
from datetime import datetime, timedelta
from typing import Iterable, Optional, List, Dict

from aiogram import types, F
from aiogram.filters import Command

# --- конфиг ---
from config import ADMIN_IDS, ALLOWED_USERS
try:
    from config import TIMEZONE  # например, "Europe/Samara"
except Exception:
    TIMEZONE = "UTC"

# --- таймзона ---
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo(TIMEZONE)
except Exception:
    TZ = None  # будем работать во времени сервера

# --- файлы хранилища ---
KNOWN_USERS_FILE = Path("known_users.json")
REMINDERS_FILE   = Path("reminders.json")

# --- утилиты авторизации ---
def _ints_set(items: Iterable) -> set[int]:
    try:
        return {int(x) for x in items}
    except Exception:
        return set()

def is_admin(user_id: int) -> bool:
    return int(user_id) in _ints_set(ADMIN_IDS)

def is_authorized_local(user_id: int) -> bool:
    uid = int(user_id)
    return uid in _ints_set(ADMIN_IDS) or uid in _ints_set(ALLOWED_USERS)

# --- прочие утилиты ---
def remember_user(uid: int) -> None:
    try:
        data = json.loads(KNOWN_USERS_FILE.read_text(encoding="utf-8")) if KNOWN_USERS_FILE.exists() else []
        s = set(int(x) for x in data)
        s.add(int(uid))
        KNOWN_USERS_FILE.write_text(json.dumps(sorted(s), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def load_known_users() -> set[int]:
    try:
        if KNOWN_USERS_FILE.exists():
            data = json.loads(KNOWN_USERS_FILE.read_text(encoding="utf-8"))
            return set(int(x) for x in data)
    except Exception:
        pass
    return set()

def get_broadcast_recipients() -> List[int]:
    base = _ints_set(ADMIN_IDS) | _ints_set(ALLOWED_USERS) | load_known_users()
    return sorted([uid for uid in base if is_authorized_local(uid)])

def now_tz() -> datetime:
    return datetime.now(tz=TZ) if TZ else datetime.now()

def make_aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=TZ) if (TZ and dt.tzinfo is None) else dt

def parse_time_hhmm(s: str) -> Optional[tuple[int,int]]:
    try:
        hh, mm = s.split(":")
        return int(hh), int(mm)
    except Exception:
        return None

# --- дни недели ---
RU_DOW = {"пн":0,"вт":1,"ср":2,"чт":3,"пт":4,"сб":5,"вс":6}
EN_DOW = {"mon":0,"tue":1,"wed":2,"thu":3,"fri":4,"sat":5,"sun":6}
DOW_TO_RU = ["ПН","ВТ","СР","ЧТ","ПТ","СБ","ВС"]

def parse_dow_list(token: str) -> Optional[List[int]]:
    if not token:
        return None
    token = token.strip().lower().replace(" ", "")
    res = set()
    for part in token.split(","):
        if part in RU_DOW: res.add(RU_DOW[part])
        elif part in EN_DOW: res.add(EN_DOW[part])
        else: return None
    return sorted(res) if res else None

def human_dow_list(dows: List[int]) -> str:
    return ",".join(DOW_TO_RU[d] for d in dows)

# --- хранение задач ---
def load_reminders() -> List[Dict]:
    if REMINDERS_FILE.exists():
        try:
            return json.loads(REMINDERS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []

def save_reminders(items: List[Dict]) -> None:
    REMINDERS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

# --- отправка всем ---
async def broadcast(bot, text: str):
    for uid in get_broadcast_recipients():
        try:
            await bot.send_message(uid, f"🔔 Напоминание:\n{text}")
        except Exception:
            pass

# --- расчёт повторов ---
def next_daily(dt: datetime) -> datetime: return dt + timedelta(days=1)

def next_weekly(dt: datetime, dows: List[int]) -> datetime:
    for i in range(1, 8):
        cand = dt + timedelta(days=i)
        if cand.weekday() in dows:
            return cand.replace(hour=dt.hour, minute=dt.minute, second=dt.second, microsecond=0)
    return dt + timedelta(days=7)

def next_monthly(dt: datetime, dom: int) -> datetime:
    y, m = dt.year, dt.month
    if m == 12:
        y, m = y + 1, 1
    else:
        m += 1
    last = calendar.monthrange(y, m)[1]
    d = min(dom, last)
    return dt.replace(year=y, month=m, day=d)

def describe_repeat(rep: Optional[Dict]) -> str:
    if not rep: return "one-time"
    if rep.get("freq") == "daily": return "ежедневно"
    if rep.get("freq") == "weekly": return f"еженедельно ({human_dow_list(rep.get('dows', []))})"
    if rep.get("freq") == "monthly": return f"ежемесячно (день {rep.get('dom')})"
    return "повтор?"

# --- фоновой воркер ---
_worker_started = False

async def _reminder_worker(bot, interval_sec: int = 15):
    while True:
        try:
            now = now_tz()
            items = load_reminders()
            keep: List[Dict] = []
            for it in items:
                try:
                    when = datetime.fromisoformat(it["when"])
                    if TZ and when.tzinfo is None:
                        when = when.replace(tzinfo=TZ)
                    if when <= now:
                        await broadcast(bot, it.get("text", ""))
                        rep = it.get("repeat")
                        if rep:
                            if rep["freq"] == "daily":
                                nxt = next_daily(when)
                            elif rep["freq"] == "weekly":
                                nxt = next_weekly(when, rep.get("dows", []))
                            elif rep["freq"] == "monthly":
                                nxt = next_monthly(when, int(rep.get("dom")))
                            else:
                                nxt = None
                            if nxt:
                                it["when"] = nxt.isoformat()
                                keep.append(it)
                        # one-time — не сохраняем
                    else:
                        keep.append(it)
                except Exception:
                    pass
            save_reminders(keep)
        except Exception:
            pass
        await asyncio.sleep(interval_sec)

# --- помощник для кнопки ---
def _is_reminders_button(text: str) -> bool:
    if not text:
        return False
    t = text.replace("🔔", "").strip().lower()
    return t in {"напоминания", "напоминание", "уведомления", "уведомление"}

# --- регистрация (как calc.py) ---
def register_reminders_handlers(dp, is_authorized, refuse, *, bot_instance=None):
    """
    Подключение модуля напоминаний.
    Вызов из Postavka.py:
        from reminders import register_reminders_handlers
        register_reminders_handlers(dp, is_authorized, refuse, bot_instance=bot)
    """

    # Кнопка «Напоминания» (с/без эмодзи) → мини-справка
    @dp.message(F.text.func(_is_reminders_button))
    async def reminders_button(message: types.Message):
        if not is_admin(message.from_user.id):
            await message.answer("⛔ Доступ только для админов.")
            return
        await remind_help(message)

    # Мини-справка
    @dp.message(Command("remind_help", "remind"))
    async def remind_help(message: types.Message):
        if not is_admin(message.from_user.id):
            await message.reply("⛔ Команда только для админов.")
            return
        tz_note = f"{TIMEZONE}" if TZ else "server time"
        text = (
            "*Напоминания — справка*\n\n"
            "Разовые:\n"
            "• `/remindall YYYY-MM-DD HH:MM Текст`\n\n"
            "Регулярные:\n"
            "• `/remindall_daily HH:MM Текст`\n"
            "• `/remindall_weekly ДНИ HH:MM Текст` (дни: `пн,вт,ср,чт,пт,сб,вс` или `mon,tue,...`)\n"
            "• `/remindall_monthly DD HH:MM Текст` (день 1–31)\n\n"
            "Управление:\n"
            "• `/reminders` — список\n"
            "• `/delreminder ID` — удалить\n\n"
            f"_Время интерпретируется в TZ: *{tz_note}*._"
        )
        await message.reply(text, parse_mode="Markdown")

    # Разовая рассылка
    @dp.message(Command("remindall"))
    async def remindall_once(message: types.Message):
        if not is_admin(message.from_user.id):
            await message.reply("⛔ Команда только для админов."); return

        parts = (message.text or "").split(maxsplit=3)
        if len(parts) < 4:
            await message.reply("Использование: `/remindall YYYY-MM-DD HH:MM Текст`", parse_mode="Markdown"); return
        _, date_str, time_str, text = parts[0], parts[1], parts[2], parts[3]

        try:
            y, m, d = map(int, date_str.split("-"))
            hh, mm = map(int, time_str.split(":"))
            run_at = make_aware(datetime(y, m, d, hh, mm))
        except Exception:
            await message.reply("Дата/время: `YYYY-MM-DD HH:MM`.", parse_mode="Markdown"); return

        if run_at <= now_tz():
            await message.reply("Время уже прошло. Укажи будущее время."); return

        items = load_reminders()
        base = f"ONE-{y:04d}{m:02d}{d:02d}{hh:02d}{mm:02d}"
        num = len([1 for it in items if str(it.get("id","")).startswith(base)])
        rem_id = f"{base}-{num}"

        items.append({"id": rem_id, "when": run_at.isoformat(), "text": text})
        save_reminders(items)

        await message.reply(
            f"✅ Разовое на *{y:04d}-{m:02d}-{d:02d} {hh:02d}:{mm:02d}* ({TIMEZONE})\nID: `{rem_id}`\nТекст:\n```\n{text}\n```",
            parse_mode="Markdown"
        )

    # Ежедневно
    @dp.message(Command("remindall_daily"))
    async def remindall_daily(message: types.Message):
        if not is_admin(message.from_user.id):
            await message.reply("⛔ Команда только для админов."); return

        args = (message.text or "").split(maxsplit=2)
        if len(args) < 3:
            await message.reply("Использование: `/remindall_daily HH:MM Текст`", parse_mode="Markdown"); return
        time_str, text = args[1], args[2]
        hm = parse_time_hhmm(time_str)
        if not hm:
            await message.reply("Время: `HH:MM`.", parse_mode="Markdown"); return
        hh, mm = hm

        now = now_tz()
        start = make_aware(datetime(now.year, now.month, now.day, hh, mm))
        if start <= now:
            start += timedelta(days=1)

        items = load_reminders()
        base = f"DLY-{hh:02d}{mm:02d}"
        num = len([1 for it in items if str(it.get("id","")).startswith(base)])
        rem_id = f"{base}-{num}"

        items.append({"id": rem_id, "when": start.isoformat(), "text": text, "repeat": {"freq": "daily"}})
        save_reminders(items)

        await message.reply(
            f"✅ Ежедневно в *{hh:02d}:{mm:02d}* ({TIMEZONE})\nПервый запуск: *{start.strftime('%Y-%m-%d %H:%M')}*\nID: `{rem_id}`",
            parse_mode="Markdown"
        )

    # Еженедельно
    @dp.message(Command("remindall_weekly"))
    async def remindall_weekly(message: types.Message):
        if not is_admin(message.from_user.id):
            await message.reply("⛔ Команда только для админов."); return

        parts = (message.text or "").split(maxsplit=3)
        if len(parts) < 4:
            await message.reply("Использование: `/remindall_weekly пн,ср 10:00 Текст`", parse_mode="Markdown"); return
        dows_token, time_str, text = parts[1], parts[2], parts[3]

        dows = parse_dow_list(dows_token)
        hm = parse_time_hhmm(time_str)
        if not dows or not hm:
            await message.reply("Дни: `пн,вт,...` или `mon,tue,...`; время: `HH:MM`.", parse_mode="Markdown"); return
        hh, mm = hm

        now = now_tz()
        candidate = make_aware(datetime(now.year, now.month, now.day, hh, mm))
        if candidate <= now or candidate.weekday() not in dows:
            for i in range(1, 8):
                cand = candidate + timedelta(days=i)
                if cand.weekday() in dows:
                    candidate = cand; break

        items = load_reminders()
        base = f"WKY-{human_dow_list(dows)}-{hh:02d}{mm:02d}"
        num = len([1 for it in items if str(it.get("id","")).startswith(base)])
        rem_id = f"{base}-{num}"

        items.append({"id": rem_id, "when": candidate.isoformat(), "text": text, "repeat": {"freq": "weekly", "dows": dows}})
        save_reminders(items)

        await message.reply(
            f"✅ Еженедельно *{human_dow_list(dows)}* в *{hh:02d}:{mm:02d}* ({TIMEZONE})\n"
            f"Первый запуск: *{candidate.strftime('%Y-%m-%d %H:%M')}*\nID: `{rem_id}`",
            parse_mode="Markdown"
        )

    # Ежемесячно
    @dp.message(Command("remindall_monthly"))
    async def remindall_monthly(message: types.Message):
        if not is_admin(message.from_user.id):
            await message.reply("⛔ Команда только для админов."); return

        parts = (message.text or "").split(maxsplit=3)
        if len(parts) < 4:
            await message.reply("Использование: `/remindall_monthly DD 09:00 Текст`", parse_mode="Markdown"); return
        dd_str, time_str, text = parts[1], parts[2], parts[3]

        try:
            dd = int(dd_str)
            if not (1 <= dd <= 31): raise ValueError
        except Exception:
            await message.reply("День месяца должен быть 1–31.", parse_mode="Markdown"); return

        hm = parse_time_hhmm(time_str)
        if not hm:
            await message.reply("Время: `HH:MM`.", parse_mode="Markdown"); return
        hh, mm = hm

        now = now_tz()
        y, m = now.year, now.month
        last = calendar.monthrange(y, m)[1]
        d = min(dd, last)
        cand = make_aware(datetime(y, m, d, hh, mm))
        if cand <= now:
            if m == 12: y, m = y+1, 1
            else: m += 1
            last = calendar.monthrange(y, m)[1]
            d = min(dd, last)
            cand = make_aware(datetime(y, m, d, hh, mm))

        items = load_reminders()
        base = f"MTH-{dd:02d}-{hh:02d}{mm:02d}"
        num = len([1 for it in items if str(it.get("id","")).startswith(base)])
        rem_id = f"{base}-{num}"

        items.append({"id": rem_id, "when": cand.isoformat(), "text": text, "repeat": {"freq": "monthly", "dom": dd}})
        save_reminders(items)

        await message.reply(
            f"✅ Ежемесячно *день {dd}* в *{hh:02d}:{mm:02d}* ({TIMEZONE})\n"
            f"Первый запуск: *{cand.strftime('%Y-%m-%d %H:%M')}*\nID: `{rem_id}`",
            parse_mode="Markdown"
        )

    # Список
    @dp.message(Command("reminders"))
    async def remind_list(message: types.Message):
        if not is_admin(message.from_user.id):
            await message.reply("⛔ Команда только для админов."); return

        items = load_reminders()
        if not items:
            await message.reply("Запланированных напоминаний нет."); return

        def sort_key(it: Dict):
            try:
                dt = datetime.fromisoformat(it["when"])
                if TZ and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=TZ)
                return dt
            except Exception:
                return datetime.max

        items.sort(key=sort_key)
        lines = []
        for it in items:
            rep = it.get("repeat")
            when = datetime.fromisoformat(it["when"])
            if TZ and when.tzinfo is None:
                when = when.replace(tzinfo=TZ)
            when_str = when.astimezone(TZ).strftime("%Y-%m-%d %H:%M") if TZ else when.strftime("%Y-%m-%d %H:%M")
            lines.append(f"- `{it['id']}` — *{when_str}* — {describe_repeat(rep)} — {it.get('text','')}")
        await message.reply("*Напоминания:*\n" + "\n".join(lines), parse_mode="Markdown")

    # Удаление
    @dp.message(Command("delreminder"))
    async def remind_delete(message: types.Message):
        if not is_admin(message.from_user.id):
            await message.reply("⛔ Команда только для админов."); return

        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.reply("Использование: `/delreminder ID`", parse_mode="Markdown"); return
        rem_id = parts[1].strip()

        items = load_reminders()
        new_items = [it for it in items if it.get("id") != rem_id]
        if len(new_items) == len(items):
            await message.reply(f"Напоминание `{rem_id}` не найдено.", parse_mode="Markdown"); return
        save_reminders(new_items)
        await message.reply(f"🗑 Напоминание `{rem_id}` удалено.", parse_mode="Markdown")

    # --- запуск фонового воркера на старте dp ---
    async def _on_startup():
        global _worker_started
        if not _worker_started:
            _worker_started = True
            bot = bot_instance or dp.bot
            asyncio.create_task(_reminder_worker(bot, interval_sec=15))

    dp.startup.register(_on_startup)

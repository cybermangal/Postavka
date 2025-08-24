# reminders.py — напоминания для aiogram v3 с хранением в Mongo и будильником через /cron/due
import calendar
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, List, Dict

from aiogram import types, F
from aiogram.filters import Command

from config import ADMIN_IDS, ALLOWED_USERS, TIMEZONE as TZ_NAME
from db import reminders as col

# --- таймзона ---
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo(TZ_NAME)
except Exception:
    TZ = timezone.utc

# --- утилиты авторизации ---
def _ints_set(items: Iterable) -> set[int]:
    try:
        return {int(x) for x in items}
    except Exception:
        return set()

ENV_ADMINS = _ints_set(ADMIN_IDS)
ENV_ALLOWED = _ints_set(ALLOWED_USERS)

def is_admin(user_id: int) -> bool:
    return int(user_id) in ENV_ADMINS

def now_tz() -> datetime:
    return datetime.now(TZ)

def make_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)

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

def describe_repeat(rep: Optional[Dict]) -> str:
    if not rep: return "one-time"
    if rep.get("freq") == "daily": return "ежедневно"
    if rep.get("freq") == "weekly": return f"еженедельно ({human_dow_list(rep.get('dows', []))})"
    if rep.get("freq") == "monthly": return f"ежемесячно (день {rep.get('dom')})"
    return "повтор?"

# --- повторные расчёты ---
def next_daily(dt: datetime) -> datetime: return dt + timedelta(days=1)

def next_weekly(dt: datetime, dows: List[int]) -> datetime:
    for i in range(1, 8):
        cand = dt + timedelta(days=i)
        if cand.weekday() in dows:
            return cand.replace(hour=dt.hour, minute=dt.minute, second=0, microsecond=0)
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

# ---- получатели рассылки (учитываем Mongo allowlist из bot.allowed_dynamic) ----
def _recipients(bot_instance=None) -> List[int]:
    dyn = set()
    if bot_instance is not None:
        dyn = set(getattr(bot_instance, "allowed_dynamic", set()))
    return sorted(ENV_ADMINS | ENV_ALLOWED | dyn)

# ---- основной прогон для крона ----
async def process_due_reminders(bot) -> int:
    now = now_tz()
    due = [x async for x in col.find({"when": {"$lte": now}})]
    total = 0
    users = _recipients(bot)
    for it in due:
        try:
            text = it.get("text", "")
            for uid in users:
                try:
                    await bot.send_message(uid, f"🔔 Напоминание:\n{text}")
                except Exception:
                    pass

            rep = it.get("repeat")
            if rep:
                when = it["when"]
                if isinstance(when, str):
                    when = datetime.fromisoformat(when)
                when = make_aware(when)
                if rep["freq"] == "daily":
                    nxt = next_daily(when)
                elif rep["freq"] == "weekly":
                    nxt = next_weekly(when, rep.get("dows", []))
                elif rep["freq"] == "monthly":
                    nxt = next_monthly(when, int(rep.get("dom")))
                else:
                    nxt = None

                if nxt:
                    await col.update_one({"_id": it["_id"]}, {"$set": {"when": nxt}})
                else:
                    await col.delete_one({"_id": it["_id"]})
            else:
                await col.delete_one({"_id": it["_id"]})
            total += 1
        except Exception:
            # не роняем прогон целиком
            pass
    return total

# --- кнопка распознавания ---
def _is_reminders_button(text: str) -> bool:
    if not text:
        return False
    t = text.replace("🔔", "").strip().lower()
    return t in {"напоминания", "напоминание", "уведомления", "уведомление"}

# --- регистрация хендлеров ---
def register_reminders_handlers(dp, is_authorized, refuse, *, bot_instance=None):

    @dp.message(Command("tz"))
    async def tz_cmd(message: types.Message):
        await message.reply(
            f"Текущая таймзона: `{TZ_NAME}`\nСейчас: *{now_tz().strftime('%Y-%m-%d %H:%M')}*",
            parse_mode="Markdown"
        )

    def recipients() -> List[int]:
        # локальная функция для help и т.д.
        return _recipients(bot_instance)

    @dp.message(F.text.func(_is_reminders_button))
    async def reminders_button(message: types.Message):
        if not is_admin(message.from_user.id):
            await message.answer("⛔ Доступ только для админов.")
            return
        await remind_help(message)

    @dp.message(Command("remind_help", "remind"))
    async def remind_help(message: types.Message):
        if not is_admin(message.from_user.id):
            await message.reply("⛔ Команда только для админов."); return
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
            "• `/delreminder ID` — удалить\n"
        )
        await message.reply(text, parse_mode="Markdown")

    # --- разовая ---
    @dp.message(Command("remindall"))
    async def remindall_once(message: types.Message):
        if not is_admin(message.from_user.id):
            await message.reply("⛔ Команда только для админов."); return

        parts = (message.text or "").split(maxsplit=3)
        if len(parts) < 4:
            await message.reply("Использование: `/remindall YYYY-MM-DD HH:MM Текст`", parse_mode="Markdown"); return
        date_str, time_str, text = parts[1], parts[2], parts[3]
        try:
            y, m, d = map(int, date_str.split("-"))
            hh, mm = map(int, time_str.split(":"))
            run_at = make_aware(datetime(y, m, d, hh, mm))
        except Exception:
            await message.reply("Дата/время: `YYYY-MM-DD HH:MM`.", parse_mode="Markdown"); return
        if run_at <= now_tz():
            await message.reply("Время уже прошло. Укажи будущее время."); return

        base = f"ONE-{y:04d}{m:02d}{d:02d}{hh:02d}{mm:02d}"
        num = await col.count_documents({"id": {"$regex": f"^{base}"}})
        rem_id = f"{base}-{num}"

        await col.insert_one({"id": rem_id, "when": run_at, "text": text})
        await message.reply(
            f"✅ Разовое на *{y:04d}-{m:02d}-{d:02d} {hh:02d}:{mm:02d}*\nID: `{rem_id}`\nТекст:\n```\n{text}\n```",
            parse_mode="Markdown"
        )

    # --- ежедневно ---
    @dp.message(Command("remindall_daily"))
    async def remindall_daily(message: types.Message):
        if not is_admin(message.from_user.id):
            await message.reply("⛔ Команда только для админов."); return
        args = (message.text or "").split(maxsplit=2)
        if len(args) < 3:
            await message.reply("Использование: `/remindall_daily HH:MM Текст`", parse_mode="Markdown"); return
        hm = parse_time_hhmm(args[1])
        if not hm:
            await message.reply("Время: `HH:MM`.", parse_mode="Markdown"); return
        hh, mm = hm

        now = now_tz()
        start = make_aware(datetime(now.year, now.month, now.day, hh, mm))
        if start <= now:
            start += timedelta(days=1)

        base = f"DLY-{hh:02d}{mm:02d}"
        num = await col.count_documents({"id": {"$regex": f"^{base}"}})
        rem_id = f"{base}-{num}"

        await col.insert_one({"id": rem_id, "when": start, "text": args[2], "repeat": {"freq": "daily"}})
        await message.reply(
            f"✅ Ежедневно в *{hh:02d}:{mm:02d}*\nПервый запуск: *{start.strftime('%Y-%m-%d %H:%M')}*\nID: `{rem_id}`",
            parse_mode="Markdown"
        )

    # --- еженедельно ---
    @dp.message(Command("remindall_weekly"))
    async def remindall_weekly(message: types.Message):
        if not is_admin(message.from_user.id):
            await message.reply("⛔ Команда только для админов."); return
        parts = (message.text or "").split(maxsplit=3)
        if len(parts) < 4:
            await message.reply("Использование: `/remindall_weekly пн,ср 10:00 Текст`", parse_mode="Markdown"); return
        dows = parse_dow_list(parts[1])
        hm = parse_time_hhmm(parts[2])
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

        base = f"WKY-{human_dow_list(dows)}-{hh:02d}{mm:02d}"
        num = await col.count_documents({"id": {"$regex": f"^{base}"}})
        rem_id = f"{base}-{num}"

        await col.insert_one({
            "id": rem_id,
            "when": candidate,
            "text": parts[3],
            "repeat": {"freq": "weekly", "dows": dows}
        })
        await message.reply(
            f"✅ Еженедельно *{human_dow_list(dows)}* в *{hh:02d}:{mm:02d}*\n"
            f"Первый запуск: *{candidate.strftime('%Y-%m-%d %H:%M')}*\nID: `{rem_id}`",
            parse_mode="Markdown"
        )

    # --- ежемесячно ---
    @dp.message(Command("remindall_monthly"))
    async def remindall_monthly(message: types.Message):
        if not is_admin(message.from_user.id):
            await message.reply("⛔ Команда только для админов."); return
        parts = (message.text or "").split(maxsplit=3)
        if len(parts) < 4:
            await message.reply("Использование: `/remindall_monthly DD 09:00 Текст`", parse_mode="Markdown"); return
        try:
            dd = int(parts[1])
            if not (1 <= dd <= 31): raise ValueError
        except Exception:
            await message.reply("День месяца должен быть 1–31.", parse_mode="Markdown"); return
        hm = parse_time_hhmm(parts[2])
        if not hm:
            await message.reply("Время: `HH:MM`.", parse_mode="Markdown"); return
        hh, mm = hm

        now = now_tz()
        y, m = now.year, now.month
        last = calendar.monthrange(y, m)[1]
        d = min(dd, last)
        cand = make_aware(datetime(y, m, d, hh, mm))
        if cand <= now:
            if m == 12: y, m = y + 1, 1
            else: m += 1
            last = calendar.monthrange(y, m)[1]
            d = min(dd, last)
            cand = make_aware(datetime(y, m, d, hh, mm))

        base = f"MTH-{dd:02d}-{hh:02d}{mm:02d}"
        num = await col.count_documents({"id": {"$regex": f"^{base}"}})
        rem_id = f"{base}-{num}"

        await col.insert_one({
            "id": rem_id,
            "when": cand,
            "text": parts[3],
            "repeat": {"freq": "monthly", "dom": dd}
        })
        await message.reply(
            f"✅ Ежемесячно *день {dd}* в *{hh:02d}:{mm:02d}*\n"
            f"Первый запуск: *{cand.strftime('%Y-%m-%d %H:%M')}*\nID: `{rem_id}`",
            parse_mode="Markdown"
        )

    # --- список ---
    @dp.message(Command("reminders"))
    async def remind_list(message: types.Message):
        if not is_admin(message.from_user.id):
            await message.reply("⛔ Команда только для админов."); return

        items = [x async for x in col.find().sort("when", 1)]
        if not items:
            await message.reply("Запланированных напоминаний нет."); return

        lines = []
        for it in items:
            when = it["when"]
            if isinstance(when, str):
                when = datetime.fromisoformat(when)
            when = make_aware(when)
            when_str = when.strftime("%Y-%m-%d %H:%M")
            rep = it.get("repeat")
            lines.append(f"- `{it.get('id')}` — *{when_str}* — {describe_repeat(rep)} — {it.get('text','')}")
        await message.reply("*Напоминания:*\n" + "\n".join(lines), parse_mode="Markdown")

    # --- удаление ---
    @dp.message(Command("delreminder"))
    async def remind_delete(message: types.Message):
        if not is_admin(message.from_user.id):
            await message.reply("⛔ Команда только для админов."); return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.reply("Использование: `/delreminder ID`", parse_mode="Markdown"); return
        rem_id = parts[1].strip()
        res = await col.delete_one({"id": rem_id})
        if res.deleted_count == 0:
            await message.reply(f"Напоминание `{rem_id}` не найдено.", parse_mode="Markdown")
        else:
            await message.reply(f"🗑 Напоминание `{rem_id}` удалено.", parse_mode="Markdown")

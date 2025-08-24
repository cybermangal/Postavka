import os
import io
import base64
from typing import List, Tuple, Optional

import aiohttp
from aiogram import types, F
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.filters import StateFilter

# ==== НАСТРОЙКИ GITHUB ====
GH_REPO = os.environ.get("GH_REPO", "").strip()            # "owner/repo"
GH_BRANCH = os.environ.get("GH_BRANCH", "main").strip()
GH_DOCS_PATH = os.environ.get("GH_DOCS_PATH", "docs").strip().strip("/")
GH_TOKEN = os.environ.get("GH_TOKEN", "").strip()

# Разрешённые расширения (в нижнем регистре, без точки)
ALLOWED_EXTS = {"pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "jpg", "jpeg", "png"}

# Клавиатура «назад в меню» (обычная, как и раньше)
back_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="⬅️ В меню")]],
    resize_keyboard=True,
)

def _is_allowed(name: str) -> bool:
    ext = (name.rsplit(".", 1)[-1] if "." in name else "").lower()
    return ext in ALLOWED_EXTS

def _join_path(*parts: str) -> str:
    clean = [p.strip("/").replace("\\", "/") for p in parts if p is not None and p != ""]
    return "/".join(clean)

def _parent_path(path: str) -> str:
    path = path.strip("/")
    if not path or "/" not in path:
        return ""
    return path.rsplit("/", 1)[0]

def _headers_json() -> dict:
    h = {"Accept": "application/vnd.github+json"}
    if GH_TOKEN:
        h["Authorization"] = f"Bearer {GH_TOKEN}"
    return h

def _headers_raw() -> dict:
    # Для git/blobs с Accept raw вернёт байты файла.
    h = {"Accept": "application/vnd.github.raw"}
    if GH_TOKEN:
        h["Authorization"] = f"Bearer {GH_TOKEN}"
    return h

# ===== GitHub API helpers =====

async def gh_list(path: str) -> Tuple[List[dict], List[dict]]:
    """
    Получить список директорий и файлов в path.
    Возвращает (dirs, files), где каждый — словари из GitHub Contents API.
    """
    api = f"https://api.github.com/repos/{GH_REPO}/contents/{path}?ref={GH_BRANCH}"
    async with aiohttp.ClientSession() as sess:
        async with sess.get(api, headers=_headers_json(), timeout=20) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"GitHub list error {resp.status}: {text}")
            data = await resp.json()
    if isinstance(data, dict) and data.get("type") == "file":
        # path — это файл; для списка вернём пустые (используем отдельный путь для скачивания)
        return [], []
    if not isinstance(data, list):
        return [], []
    dirs, files = [], []
    for it in data:
        if it.get("type") == "dir":
            dirs.append(it)
        elif it.get("type") == "file":
            if _is_allowed(it.get("name", "")):
                files.append(it)
    # Сортировка: папки A→Я, файлы A→Я
    dirs.sort(key=lambda x: x.get("name", "").lower())
    files.sort(key=lambda x: x.get("name", "").lower())
    return dirs, files

async def gh_get_file_bytes(path: str) -> Tuple[bytes, str]:
    """
    Получить байты файла по относительному пути в репо.
    Сначала обращаемся к /contents, если есть content — декодируем,
    если нет — идём в git/blob по sha и просим raw.
    Возвращает (bytes, filename)
    """
    contents_api = f"https://api.github.com/repos/{GH_REPO}/contents/{path}?ref={GH_BRANCH}"
    async with aiohttp.ClientSession() as sess:
        async with sess.get(contents_api, headers=_headers_json(), timeout=30) as r1:
            if r1.status != 200:
                text = await r1.text()
                raise RuntimeError(f"GitHub content error {r1.status}: {text}")
            meta = await r1.json()

        if meta.get("type") != "file":
            raise RuntimeError("Not a file")

        name = meta.get("name") or path.rsplit("/", 1)[-1]

        # Попробуем content (до ~1MB GitHub возвращает base64)
        content_b64 = meta.get("content")
        encoding = meta.get("encoding")
        if content_b64 and encoding == "base64":
            try:
                raw = base64.b64decode(content_b64)
                return raw, name
            except Exception:
                pass  # пойдём по blobs

        sha = meta.get("sha")
        if not sha:
            # fallback на download_url, но для приватных может не сработать; попробуем всё же
            dl = meta.get("download_url")
            if not dl:
                raise RuntimeError("No sha and no download_url")
            async with sess.get(dl, headers=_headers_raw(), timeout=60) as r2:
                if r2.status != 200:
                    text = await r2.text()
                    raise RuntimeError(f"GitHub download error {r2.status}: {text}")
                raw = await r2.read()
                return raw, name

        # Надёжный путь: git/blob по sha с Accept: raw — отдаст байты любого разумного размера (<100MB)
        blob_api = f"https://api.github.com/repos/{GH_REPO}/git/blobs/{sha}"
        async with sess.get(blob_api, headers=_headers_raw(), timeout=60) as r3:
            if r3.status != 200:
                text = await r3.text()
                raise RuntimeError(f"GitHub blob error {r3.status}: {text}")
            raw = await r3.read()
            return raw, name

# ===== UI helpers =====

def _build_inline_for_path(path: str, dirs: List[dict], files: List[dict]) -> InlineKeyboardMarkup:
    """
    Сформировать инлайн-клавиатуру: сначала папки, потом файлы.
    callback_data: "doc:d:<fullpath>" для папок, "doc:f:<fullpath>" для файла.
    """
    buttons: List[List[InlineKeyboardButton]] = []

    for d in dirs:
        name = d.get("name", "")
        full = _join_path(path, name)
        buttons.append([InlineKeyboardButton(text=f"📁 {name}", callback_data=f"doc:d:{full}")])

    for f in files:
        name = f.get("name", "")
        full = _join_path(path, name)
        buttons.append([InlineKeyboardButton(text=f"📄 {name}", callback_data=f"doc:f:{full}")])

    # Навигация
    parent = _parent_path(path)
    nav_row: List[InlineKeyboardButton] = []
    if parent != path:
        if parent:
            nav_row.append(InlineKeyboardButton(text="⬆️ Вверх", callback_data=f"doc:d:{parent}"))
        nav_row.append(InlineKeyboardButton(text="🏠 Корень", callback_data=f"doc:d:{GH_DOCS_PATH}"))
    if nav_row:
        buttons.append(nav_row)

    return InlineKeyboardMarkup(inline_keyboard=buttons or [[
        InlineKeyboardButton(text="🏠 Корень", callback_data=f"doc:d:{GH_DOCS_PATH}")
    ]])

# ===== Handlers =====

def register_docs_handlers(dp, is_authorized, refuse):

    # Вход в раздел — показывает корневую папку из репо
    @dp.message(StateFilter('*'), F.text == "📁 Документы")
    async def docs_menu(message: types.Message, state=None):
        if not is_authorized(message.from_user.id):
            await refuse(message); return

        if not GH_REPO:
            await message.answer(
                "❗️GitHub не настроен. Укажи переменные окружения: GH_REPO, GH_DOCS_PATH (и GH_TOKEN для приватного репо).",
                reply_markup=back_kb
            )
            return

        root = GH_DOCS_PATH or ""
        try:
            dirs, files = await gh_list(root)
            kb = _build_inline_for_path(root, dirs, files)
            await message.answer("Выбери документ или папку:", reply_markup=back_kb)
            await message.answer(f"Путь: /{root}" if root else "Путь: /", reply_markup=kb)
        except Exception as e:
            await message.answer(f"Ошибка GitHub: {e}", reply_markup=back_kb)

    # Навигация по папкам и выбор файла
    @dp.callback_query(F.data.startswith("doc:"))
    async def on_doc_cb(cb: CallbackQuery):
        if not is_authorized(cb.from_user.id):
            await cb.message.answer("⛔️ Доступ запрещён."); await cb.answer(); return

        # data формата: "doc:<kind>:<path>"
        try:
            _, kind, rest = cb.data.split(":", maxsplit=2)
        except ValueError:
            await cb.answer("Некорректные данные"); return

        path = rest.strip("/")
        if kind == "d":
            # Папка: показать содержимое
            try:
                dirs, files = await gh_list(path)
                kb = _build_inline_for_path(path, dirs, files)
                await cb.message.edit_text(f"Путь: /{path}" if path else "Путь: /")
                await cb.message.edit_reply_markup(reply_markup=kb)
            except Exception as e:
                await cb.answer("Ошибка")
                await cb.message.answer(f"Ошибка GitHub: {e}")
            return

        if kind == "f":
            # Файл: скачать и отправить
            try:
                raw, name = await gh_get_file_bytes(path)
                # Для крупных файлов Telegram может отклонить — тогда дадим ссылку
                bio = io.BytesIO(raw)
                bio.name = name  # чтобы Telegram понял имя
                await cb.message.answer_document(FSInputFile(bio), caption=f"📁 {name}")
            except Exception as e:
                # На всякий случай предложим прямую ссылку на raw (только для публичного репо)
                fallback = f"https://raw.githubusercontent.com/{GH_REPO}/{GH_BRANCH}/{path}"
                msg = f"Не удалось отправить файл: {e}"
                if GH_TOKEN:
                    msg += "\n(Файл приватный, прямая ссылка без токена не откроется.)"
                else:
                    msg += f"\nПопробуйте по ссылке: {fallback}"
                await cb.message.answer(msg)
            finally:
                await cb.answer()
            return

        await cb.answer("Неизвестное действие")

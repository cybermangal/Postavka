# docs.py — GitHub Docs (Trees API + cache) с короткими callback-токенами
import os
import time
import secrets
import logging
from typing import List, Tuple, Optional, Dict, Any, Set

import aiohttp
from aiogram import types, F
from aiogram.filters import StateFilter, Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, BufferedInputFile
)

log = logging.getLogger("docs")

# =========================
#   НАСТРОЙКИ GITHUB
# =========================
GH_REPO = os.environ.get("GH_REPO", "").strip()            # "owner/repo"
GH_BRANCH = os.environ.get("GH_BRANCH", "main").strip()
GH_DOCS_PATH = os.environ.get("GH_DOCS_PATH", "docs").strip().strip("/")
GH_TOKEN = os.environ.get("GH_TOKEN", "").strip()
GH_CACHE_TTL = int(os.environ.get("GH_CACHE_TTL", "600"))  # сек: 600 = 10 минут

# Разрешённые расширения (в нижнем регистре, без точки)
ALLOWED_EXTS: Set[str] = {"pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "jpg", "jpeg", "png"}

# Клавиатура «назад в меню»
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

def _headers(kind: str = "json") -> dict:
    if kind == "json":
        h = {"Accept": "application/vnd.github+json"}
    elif kind == "raw":
        h = {"Accept": "application/vnd.github.raw"}
    else:
        h = {}
    if GH_TOKEN:
        h["Authorization"] = f"Bearer {GH_TOKEN}"
    return h

def _require_repo() -> Optional[str]:
    if not GH_REPO or "/" not in GH_REPO:
        return "❗️GitHub не настроен. Укажи переменные: GH_REPO=owner/repo, GH_DOCS_PATH (и GH_TOKEN для приватного репо)."
    return None

# =========================
#   КЭШ ДЕРЕВА РЕПО
# =========================
# TREE_CACHE = {"expires": <ts>, "branch_sha": "<sha>", "tree": [ {type, path, sha}, ... ]}
TREE_CACHE: Dict[str, Any] = {}

async def _gh_json(url: str, kind: str = "json") -> Any:
    async with aiohttp.ClientSession() as sess:
        async with sess.get(url, headers=_headers(kind), timeout=30) as resp:
            text = await resp.text()
            if resp.status == 403 and "rate limit" in text.lower():
                raise RuntimeError(f"GitHub 403 rate limit: {text}")
            if resp.status != 200:
                raise RuntimeError(f"GitHub error {resp.status}: {text}")
            if kind == "json":
                import json
                return json.loads(text)
            else:
                return text.encode()

async def _gh_bytes(url: str) -> bytes:
    async with aiohttp.ClientSession() as sess:
        async with sess.get(url, headers=_headers("raw"), timeout=60) as resp:
            if resp.status == 403:
                t = await resp.text()
                raise RuntimeError(f"GitHub 403: {t}")
            if resp.status != 200:
                t = await resp.text()
                raise RuntimeError(f"GitHub error {resp.status}: {t}")
            return await resp.read()

async def _get_branch_commit_sha() -> str:
    url = f"https://api.github.com/repos/{GH_REPO}/branches/{GH_BRANCH}"
    data = await _gh_json(url, "json")
    sha = data.get("commit", {}).get("sha")
    if not sha:
        raise RuntimeError("No commit sha for branch")
    return sha

async def _get_tree_recursive(commit_sha: str) -> List[Dict[str, Any]]:
    url = f"https://api.github.com/repos/{GH_REPO}/git/trees/{commit_sha}?recursive=1"
    data = await _gh_json(url, "json")
    tree = data.get("tree", [])
    norm = []
    for it in tree:
        t = it.get("type")  # "blob" | "tree"
        p = it.get("path")
        sha = it.get("sha")
        if not (t and p and sha):
            continue
        norm.append({"type": t, "path": p, "sha": sha})
    return norm

async def ensure_tree_cache(force: bool = False) -> None:
    now = time.time()
    if not force and TREE_CACHE and TREE_CACHE.get("expires", 0) > now:
        return
    commit_sha = await _get_branch_commit_sha()
    tree = await _get_tree_recursive(commit_sha)
    TREE_CACHE.clear()
    TREE_CACHE.update({
        "expires": now + GH_CACHE_TTL,
        "branch_sha": commit_sha,
        "tree": tree,
    })
    log.info("Docs: tree cache refreshed, %d entries", len(tree))

def _list_from_tree(current_path: str) -> Tuple[List[str], List[str]]:
    current_path = current_path.strip("/")
    prefix = f"{current_path}/" if current_path else ""
    tree = TREE_CACHE.get("tree", [])
    dir_set: Set[str] = set()
    file_list: List[str] = []

    for it in tree:
        path = it["path"]
        if not path.startswith(prefix):
            continue
        rest = path[len(prefix):]
        if "/" in rest:
            dir_set.add(rest.split("/", 1)[0])
        else:
            if it["type"] == "blob" and _is_allowed(rest):
                file_list.append(rest)

    return sorted(dir_set, key=str.lower), sorted(file_list, key=str.lower)

def _find_blob_sha(full_path: str) -> Optional[str]:
    full_path = full_path.strip("/")
    for it in TREE_CACHE.get("tree", []):
        if it["type"] == "blob" and it["path"] == full_path:
            return it["sha"]
    return None

async def gh_get_file_bytes_by_blob_sha(blob_sha: str) -> bytes:
    url = f"https://api.github.com/repos/{GH_REPO}/git/blobs/{blob_sha}"
    return await _gh_bytes(url)

# =========================
#  КОРОТКИЕ CALLBACK DATA
# =========================
# Telegram ограничивает callback_data 1..64 байт.
# Делаем токены fixed-size, а пути храним в памяти.
DOCS_TOKEN_TTL = int(os.environ.get("DOCS_TOKEN_TTL", "900"))  # 15 минут
_TOKEN_MAP: Dict[str, Dict[str, Any]] = {}  # token -> {"path": str, "ts": float}

def _cleanup_tokens():
    now = time.time()
    dead = [t for t, v in _TOKEN_MAP.items() if v.get("ts", 0) + DOCS_TOKEN_TTL < now]
    for t in dead:
        _TOKEN_MAP.pop(t, None)
    if dead:
        log.debug("Docs: cleaned %d expired tokens", len(dead))

def _token_for_path(path: str) -> str:
    """
    Выдаёт короткий токен (<= 16 байт) и кладёт соответствие token->path в память.
    """
    _cleanup_tokens()
    # 12 символов достаточно ( ~72 бита энтропии)
    token = secrets.token_urlsafe(9)  # ~12 символов
    _TOKEN_MAP[token] = {"path": path, "ts": time.time()}
    return token

def _path_from_token(token: str) -> Optional[str]:
    row = _TOKEN_MAP.get(token)
    if not row:
        return None
    if row["ts"] + DOCS_TOKEN_TTL < time.time():
        _TOKEN_MAP.pop(token, None)
        return None
    # обновим таймштамп при обращении, чтобы не отваливалось во время навигации
    row["ts"] = time.time()
    return row["path"]

# =========================
#      UI helpers
# =========================

def _build_inline_for_path(path: str, dirs: List[str], files: List[str]) -> InlineKeyboardMarkup:
    buttons: List[List[InlineKeyboardButton]] = []

    for d in dirs:
        full = _join_path(path, d)
        tok = _token_for_path(full)
        buttons.append([InlineKeyboardButton(text=f"📁 {d}", callback_data=f"doc:d:{tok}")])

    for f in files:
        full = _join_path(path, f)
        tok = _token_for_path(full)
        buttons.append([InlineKeyboardButton(text=f"📄 {f}", callback_data=f"doc:f:{tok}")])

    parent = _parent_path(path)
    nav_row: List[InlineKeyboardButton] = []
    if parent != path:
        if parent:
            tok_up = _token_for_path(parent)
            nav_row.append(InlineKeyboardButton(text="⬆️ Вверх", callback_data=f"doc:d:{tok_up}"))
        home = GH_DOCS_PATH or ""
        tok_home = _token_for_path(home)
        nav_row.append(InlineKeyboardButton(text="🏠 Корень", callback_data=f"doc:d:{tok_home}"))
    if nav_row:
        buttons.append(nav_row)

    if not buttons:
        home = GH_DOCS_PATH or ""
        tok_home = _token_for_path(home)
        buttons = [[InlineKeyboardButton(text="🏠 Корень", callback_data=f"doc:d:{tok_home}")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def _send_path_message(message: types.Message, path: str):
    dirs, files = _list_from_tree(path)
    kb = _build_inline_for_path(path, dirs, files)
    caption = f"Выбери документ или папку:\nПуть: /{path}" if path else "Выбери документ или папку:\nПуть: /"
    await message.answer(caption, reply_markup=kb)

# =========================
#       HANDLERS
# =========================

def register_docs_handlers(dp, is_authorized, refuse):

    @dp.message(StateFilter('*'), F.text == "📁 Документы")
    async def docs_menu(message: types.Message, state=None):
        if not is_authorized(message.from_user.id):
            await refuse(message); return

        err = _require_repo()
        if err:
            await message.answer(err, reply_markup=back_kb); return

        try:
            await ensure_tree_cache(force=False)
        except Exception as e:
            txt = str(e)
            if "rate limit" in txt.lower():
                await message.answer(
                    "⛔ GitHub rate limit. Добавь `GH_TOKEN` (PAT) в переменные Render, "
                    "или подожди час. Ошибка:\n" + txt,
                    reply_markup=back_kb
                )
                return
            await message.answer(f"Ошибка GitHub: {e}", reply_markup=back_kb)
            return

        root = GH_DOCS_PATH or ""
        log.info("Docs: open requested by %s", message.from_user.id)
        await _send_path_message(message, root)

    @dp.message(Command("docs"))
    async def docs_cmd(message: types.Message):
        if not is_authorized(message.from_user.id):
            await refuse(message); return
        err = _require_repo()
        if err:
            await message.answer(err, reply_markup=back_kb); return
        try:
            await ensure_tree_cache(force=False)
        except Exception as e:
            await message.answer(f"Ошибка GitHub: {e}", reply_markup=back_kb)
            return
        root = GH_DOCS_PATH or ""
        await _send_path_message(message, root)

    @dp.callback_query(F.data.startswith("doc:"))
    async def on_doc_cb(cb: CallbackQuery):
        if not is_authorized(cb.from_user.id):
            await cb.message.answer("⛔️ Доступ запрещён."); await cb.answer(); return

        try:
            _, kind, token = cb.data.split(":", maxsplit=2)
        except ValueError:
            await cb.answer("Некорректные данные"); return

        path = _path_from_token(token)
        if not path:
            # токен устарел — обновим кэш и вернёмся на корень
            try:
                await ensure_tree_cache(force=False)
            except Exception:
                pass
            home = GH_DOCS_PATH or ""
            dirs, files = _list_from_tree(home)
            kb = _build_inline_for_path(home, dirs, files)
            await cb.message.edit_text("Ссылка устарела. Обновил список.\nПуть: /" + (home or ""))
            await cb.message.edit_reply_markup(reply_markup=kb)
            await cb.answer()
            return

        if kind == "d":
            try:
                await ensure_tree_cache(force=False)
                dirs, files = _list_from_tree(path)
                kb = _build_inline_for_path(path, dirs, files)
                caption = f"Выбери документ или папку:\nПуть: /{path}" if path else "Выбери документ или папку:\nПуть: /"
                await cb.message.edit_text(caption)
                await cb.message.edit_reply_markup(reply_markup=kb)
            except Exception as e:
                await cb.answer("Ошибка")
                await cb.message.answer(f"Ошибка GitHub: {e}")
            return

        if kind == "f":
            try:
                await ensure_tree_cache(force=False)
                sha = _find_blob_sha(path)
                if not sha:
                    await cb.answer("Файл не найден"); return
                raw = await gh_get_file_bytes_by_blob_sha(sha)
                name = path.rsplit("/", 1)[-1]
                await cb.message.answer_document(
                    BufferedInputFile(raw, filename=name),
                    caption=f"📁 {name}"
                )
            except Exception as e:
                fallback = f"https://raw.githubusercontent.com/{GH_REPO}/{GH_BRANCH}/{path}"
                msg = f"Не удалось отправить файл: {e}"
                if GH_TOKEN:
                    msg += "\n(Файл может быть приватным; прямая ссылка без токена не откроется.)"
                else:
                    msg += f"\nЕсли репозиторий публичный, попробуйте ссылку: {fallback}"
                await cb.message.answer(msg)
            finally:
                await cb.answer()
            return

        await cb.answer("Неизвестное действие")

    # Текстовый ввод имени файла — ищем в кэше и отдаём
    @dp.message(StateFilter('*'), F.text.func(lambda s: isinstance(s, str) and "." in s))
    async def docs_text_lookup(message: types.Message):
        if not is_authorized(message.from_user.id):
            await refuse(message); return

        name = (message.text or "").strip()
        if len(name) < 3:
            return

        try:
            await ensure_tree_cache(force=False)
        except Exception:
            return

        matches: List[str] = []
        low = name.lower()
        for it in TREE_CACHE.get("tree", []):
            if it["type"] != "blob":
                continue
            base = it["path"].rsplit("/", 1)[-1]
            if base.lower() == low and _is_allowed(base):
                matches.append(it["path"])

        if not matches:
            return

        if len(matches) > 1:
            buttons = []
            for p in matches[:10]:
                tok = _token_for_path(p)
                buttons.append([InlineKeyboardButton(text=p, callback_data=f"doc:f:{tok}")])
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
            await message.answer("Нашёл несколько файлов, выбери нужный:", reply_markup=kb)
            return

        path = matches[0]
        sha = _find_blob_sha(path)
        if not sha:
            await message.answer("Не удалось найти файл."); return
        try:
            raw = await gh_get_file_bytes_by_blob_sha(sha)
            fname = path.rsplit("/", 1)[-1]
            await message.answer_document(BufferedInputFile(raw, filename=fname), caption=f"📁 {fname}")
        except Exception as e:
            fallback = f"https://raw.githubusercontent.com/{GH_REPO}/{GH_BRANCH}/{path}"
            msg = f"Не удалось отправить файл: {e}"
            if GH_TOKEN:
                msg += "\n(Файл может быть приватным; прямая ссылка без токена не откроется.)"
            else:
                msg += f"\nЕсли репозиторий публичный, попробуйте ссылку: {fallback}"
            await message.answer(msg)

    # «⬅️ В меню»
    @dp.message(StateFilter('*'), F.text == "⬅️ В меню")
    async def back_to_menu(message: types.Message, state=None):
        kb = getattr(message.bot, "main_kb", None)
        await message.answer("Главное меню:", reply_markup=kb)

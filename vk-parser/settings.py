"""Local settings; on Windows the bot token is protected for the current user."""
import base64
import ctypes
import getpass
import json
import os
from pathlib import Path

import requests

from extract import write_json

ROOT = Path(__file__).resolve().parent
DEFAULT_PATH = ROOT / "settings.json"
DEFAULTS = {"url": "https://vk.ru/cvetyurala", "limit": 10, "interval": 60,
            "archive": "archive", "headless": False, "telegram": {}}


def load_settings(path=None):
    path = Path(path or DEFAULT_PATH)
    return {**DEFAULTS, **(json.loads(path.read_text(encoding="utf-8")) if path.exists() else {})}


def protect_token(token, decrypt=False):
    if os.name != "nt":
        raise RuntimeError("На этой системе задайте TELEGRAM_BOT_TOKEN в окружении")
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte))]
    data = base64.b64decode(token) if decrypt else token.encode("utf-8")
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise RuntimeError("Не удалось открыть/сохранить защищённый токен Windows")
    try:
        result = ctypes.string_at(target.data, target.size)
        return result.decode("utf-8") if decrypt else base64.b64encode(result).decode("ascii")
    finally:
        kernel = ctypes.WinDLL("kernel32")
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


def get_token(settings=None):
    value = os.environ.get("TELEGRAM_BOT_TOKEN")
    if value:
        return value
    encrypted = (settings or load_settings()).get("telegram", {}).get("token_dpapi")
    return protect_token(encrypted, decrypt=True) if encrypted else None


def api_read(token, method, params=None, session=requests):
    try:
        response = session.get(f"https://api.telegram.org/bot{token}/{method}", params=params or {}, timeout=(15, 30))
        value = response.json()
        if not isinstance(value, dict) or not value.get("ok"):
            code = value.get("error_code", response.status_code) if isinstance(value, dict) else response.status_code
            raise RuntimeError(f"Telegram отклонил {method}: код {code}")
        return value["result"]
    except (requests.RequestException, ValueError):
        raise RuntimeError(f"Нет подтверждённого ответа Telegram на {method}. Проверьте сеть.") from None


def channel_updates(token):
    updates = api_read(token, "getUpdates", {"timeout": 0})
    chats = {}
    for update in updates:
        for field in ("channel_post", "edited_channel_post", "my_chat_member"):
            chat = update.get(field, {}).get("chat", {})
            if chat.get("type") == "channel":
                chats[str(chat["id"])] = chat
    return list(chats.values())


def setup_telegram(path=None, input_fn=input, secret_fn=getpass.getpass):
    path = Path(path or DEFAULT_PATH)
    settings = load_settings(path)
    print("Создайте бота у https://t.me/BotFather командой /newbot.")
    print("Добавьте его администратором канала с правом публикации сообщений.")
    token = secret_fn("Токен бота (ввод скрыт; не отправляйте его в чат): ").strip()
    me = api_read(token, "getMe")
    print(f"Бот: @{me.get('username', me['id'])}")
    target = input_fn("Канал: @username или числовой ID; для поиска частного канала введите find: ").strip()
    if target.casefold() == "find":
        print("Сначала опубликуйте любой пост в своём канале, где бот уже администратор.")
        input_fn("После публикации нажмите Enter: ")
        chats = channel_updates(token)
        if not chats:
            raise ValueError("Канал не найден в обновлениях. Проверьте права бота или укажите ID канала вручную.")
        for index, chat in enumerate(chats, 1):
            print(f"{index}. {chat.get('title', '')} ({chat['id']})")
        selected = int(input_fn("Номер канала: "))
        if selected < 1 or selected > len(chats):
            raise ValueError("Нет такого номера канала")
        target = str(chats[selected - 1]["id"])
    chat = api_read(token, "getChat", {"chat_id": target})
    if chat.get("type") != "channel":
        raise ValueError("Для этого подключения нужен Telegram-канал")
    rights = api_read(token, "getChatMember", {"chat_id": chat["id"], "user_id": me["id"]})
    if rights.get("status") != "creator" and not (rights.get("status") == "administrator" and rights.get("can_post_messages")):
        raise ValueError("Дайте боту право публиковать сообщения в канале и повторите подключение")
    telegram = {"chat_id": str(chat["id"]), "chat_title": chat.get("title", ""),
                "bot_id": me["id"], "bot_username": me.get("username", "")}
    if os.name == "nt":
        telegram["token_dpapi"] = protect_token(token)
    else:
        os.environ["TELEGRAM_BOT_TOKEN"] = token
        print("Для следующего запуска задайте TELEGRAM_BOT_TOKEN в окружении.")
    settings["telegram"] = telegram
    write_json(path, settings)
    print(f"Подключён канал: {chat.get('title', '')} ({chat['id']}). Публикаций при настройке не выполнялось.")
    return settings

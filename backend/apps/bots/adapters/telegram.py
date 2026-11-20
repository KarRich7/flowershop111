"""Адаптер Telegram (aiogram 3, обычный чат-бот без Mini App / Web App).
Входящие сообщения и нажатия кнопок передаются в общий BotEngine, ответы рендерятся
в сообщения Telegram с inline-клавиатурой."""
import asyncio
import logging
from pathlib import Path

from aiogram import Dispatcher
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.types import (CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                           Message, ReplyKeyboardMarkup, ReplyKeyboardRemove)
from asgiref.sync import sync_to_async
from django.conf import settings

from apps.bots import telegram_net
from apps.bots.engine import BotEngine, Incoming

logger = logging.getLogger("bots.telegram")
LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0")


def _url_ok(url):
    return url.startswith("https://") or (url.startswith("http://") and not any(h in url for h in LOCAL_HOSTS))


def build_markup(out):
    rows, reply_buttons, extra = [], [], []
    for row in out.buttons:
        r = []
        for b in row:
            if b.request_contact:
                reply_buttons.append(KeyboardButton(text="📱 Отправить мой номер", request_contact=True))
            elif b.request_location:
                reply_buttons.append(KeyboardButton(text="📍 Отправить геопозицию", request_location=True))
            elif b.url:
                if _url_ok(b.url):
                    r.append(InlineKeyboardButton(text=b.text, url=b.url))
                else:  # Telegram отклоняет localhost-ссылки в кнопках
                    extra.append(f"{b.text}: {b.url}")
            elif b.payload:
                r.append(InlineKeyboardButton(text=b.text[:64], callback_data=b.payload[:64]))
        if r:
            rows.append(r)
    inline = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
    reply = ReplyKeyboardMarkup(keyboard=[[b] for b in reply_buttons], resize_keyboard=True,
                                one_time_keyboard=True) if reply_buttons else None
    return inline, reply, extra


async def render(bot, chat_id, outs):
    for out in outs:
        inline, reply, extra = build_markup(out)
        text = "\n".join([out.text] + extra)
        if reply:  # клавиатура «отправить номер / геопозицию» — отдельным сообщением
            await bot.send_message(chat_id, "Можно воспользоваться кнопкой ниже 👇", reply_markup=reply)
        photo_path = Path(settings.MEDIA_ROOT) / out.photo if out.photo else None
        if photo_path and photo_path.exists():
            await bot.send_photo(chat_id, FSInputFile(photo_path), caption=text[:1024], reply_markup=inline)
        else:
            await bot.send_message(chat_id, text[:4096], reply_markup=inline, disable_web_page_preview=True)


RESTART_HINT = "docker compose up -d --force-recreate backend celery-worker"


def group_chat_reply(chat_id, text, joined_ids, bot_id):
    """Сообщение в группе: там бот не продаёт, а только подсказывает номер группы для уведомлений сотрудникам —
    когда его добавили в группу или написали /chatid. На остальное молчит."""
    words = (text or "").strip().split()
    cmd = words[0].split("@")[0].lower() if words else ""
    if bot_id in joined_ids or cmd == "/chatid":
        return (f"Номер этого чата: {chat_id}\n\n"
                "Чтобы сюда приходили уведомления о новых заказах и обращениях покупателей, впишите на сервере "
                f"в файл .env строку:\nTELEGRAM_STAFF_CHAT_ID={chat_id}\nи перезапустите: {RESTART_HINT} telegram-bot")
    return None


def build_dispatcher(engine=None):
    engine = engine or BotEngine("telegram")
    dp = Dispatcher()
    handle = sync_to_async(engine.handle, thread_sensitive=True)

    @dp.message()
    async def on_message(m: Message):
        if m.chat.type != "private":  # группа сотрудников: только подсказка с номером
            reply = group_chat_reply(m.chat.id, m.text, [u.id for u in (m.new_chat_members or [])], m.bot.id)
            if reply:
                await m.answer(reply)
            return
        inc = Incoming(
            channel="telegram", user_id=str(m.from_user.id), chat_id=str(m.chat.id), text=m.text or "",
            contact_phone=m.contact.phone_number if m.contact else None,
            location=(m.location.latitude, m.location.longitude) if m.location else None,
            display_name=m.from_user.full_name or "", username=m.from_user.username or "",
        )
        outs = await handle(inc)
        if m.contact or m.location:
            await m.answer("Получено", reply_markup=ReplyKeyboardRemove())
        await render(m.bot, m.chat.id, outs)

    @dp.callback_query()
    async def on_callback(c: CallbackQuery):
        await c.answer()
        if not c.message or c.message.chat.type != "private":
            return
        inc = Incoming(
            channel="telegram", user_id=str(c.from_user.id), chat_id=str(c.message.chat.id), payload=c.data,
            display_name=c.from_user.full_name or "", username=c.from_user.username or "",
        )
        outs = await handle(inc)
        await render(c.bot, c.message.chat.id, outs)

    return dp


async def run_polling():
    bot = telegram_net.aiogram_bot()
    if settings.TELEGRAM_PROXY:
        logger.info("Telegram: соединение через прокси %s", telegram_net.proxy_display())
    try:
        me = await bot.get_me()
    except TelegramUnauthorizedError:
        logger.error("Telegram отклонил TELEGRAM_BOT_TOKEN (Unauthorized): проверьте токен в @BotFather")
        await bot.session.close()
        raise
    except Exception as e:  # noqa: BLE001 — сеть, таймаут, ошибка прокси (python-socks): подсказка в журнал
        logger.error("%s [%s]", telegram_net.no_connection_hint(), type(e).__name__)
        await bot.session.close()
        await asyncio.sleep(30)  # не перезапускаться слишком часто, пока нет связи
        raise
    logger.info("Telegram bot @%s started (long polling)", me.username)
    await build_dispatcher().start_polling(bot)


def run():
    asyncio.run(run_polling())

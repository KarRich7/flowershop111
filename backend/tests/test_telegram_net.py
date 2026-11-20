"""Связь с Telegram через прокси (TELEGRAM_PROXY) и команда проверки ботов check_bots."""
import io
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.bots import telegram_net
from apps.notifications.tasks import send_telegram


class _Resp:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


@override_settings(TELEGRAM_PROXY="")
def test_no_proxy_by_default():
    assert telegram_net.requests_proxies() is None
    assert telegram_net.proxy_display() == ""


@override_settings(TELEGRAM_PROXY="socks5://user:secret@1.2.3.4:1080")
def test_socks5_proxy_resolves_dns_remotely_and_hides_password():
    assert telegram_net.requests_proxies() == {"http": "socks5h://user:secret@1.2.3.4:1080",
                                               "https": "socks5h://user:secret@1.2.3.4:1080"}
    assert telegram_net.proxy_display() == "socks5://1.2.3.4:1080"


@override_settings(TELEGRAM_BOT_TOKEN="123:abc", TELEGRAM_PROXY="http://u:p@5.6.7.8:3128",
                   TELEGRAM_API_BASE="https://tg.example.com")
def test_send_telegram_goes_through_proxy_and_custom_api_base():
    with mock.patch("apps.bots.telegram_net.requests.request", return_value=_Resp({"ok": True})) as req:
        send_telegram("42", "Новый заказ")
    method, url = req.call_args.args
    assert method == "POST" and url == "https://tg.example.com/bot123:abc/sendMessage"
    assert req.call_args.kwargs["proxies"] == {"http": "http://u:p@5.6.7.8:3128", "https": "http://u:p@5.6.7.8:3128"}
    assert req.call_args.kwargs["json"]["chat_id"] == "42"


@override_settings(TELEGRAM_BOT_TOKEN="123:abc", TELEGRAM_PROXY="")
def test_send_telegram_error_is_raised():
    with mock.patch("apps.bots.telegram_net.requests.request", return_value=_Resp({"ok": False, "description": "chat not found"})):
        with pytest.raises(RuntimeError, match="chat not found"):
            send_telegram("42", "x")


@override_settings(TELEGRAM_BOT_TOKEN="123:abc", TELEGRAM_PROXY="socks5://u:p@1.2.3.4:1080",
                   TELEGRAM_API_BASE="https://tg.example.com")
def test_aiogram_bot_uses_proxy_and_api_base():
    bot = telegram_net.aiogram_bot()
    assert bot.session.proxy == "socks5://u:p@1.2.3.4:1080"
    assert bot.session.api.api_url("123:abc", "getMe") == "https://tg.example.com/bot123:abc/getMe"


def _vk_fake(group_id=233702651):
    def fake(url, data=None, timeout=None):
        method = url.rsplit("/", 1)[-1]
        return _Resp({
            "groups.getById": {"response": {"groups": [{"id": group_id, "name": "Цветы", "screen_name": "shop"}]}},
            "groups.getTokenPermissions": {"response": {"permissions": [{"name": "manage"}, {"name": "messages"},
                                                                       {"name": "photos"}]}},
            "groups.getLongPollSettings": {"response": {"is_enabled": True, "api_version": "5.199",
                                                        "events": {"message_new": 1}}},
            "groups.getLongPollServer": {"response": {"server": "s", "key": "k", "ts": "1"}},
        }[method])
    return fake


@pytest.mark.django_db
@override_settings(TELEGRAM_BOT_TOKEN="123:abc", TELEGRAM_PROXY="", TELEGRAM_BOT_USERNAME="", TELEGRAM_STAFF_CHAT_ID="",
                   VK_GROUP_TOKEN="vk1.a.key", VK_GROUP_ID="233702651")
def test_check_bots_all_ok():
    out = io.StringIO()
    with mock.patch("apps.bots.telegram_net.requests.request",
                    return_value=_Resp({"ok": True, "result": {"username": "cvety_bot"}})), \
            mock.patch("apps.bots.management.commands.check_bots.requests.post", side_effect=_vk_fake()):
        call_command("check_bots", stdout=out)
    text = out.getvalue()
    assert "бот @cvety_bot отвечает" in text
    assert "VK_GROUP_ID совпадает" in text and "подключение бота к ВК работает" in text
    assert "✘" not in text


@pytest.mark.django_db
@override_settings(TELEGRAM_BOT_TOKEN="123:abc", TELEGRAM_PROXY="", VK_GROUP_TOKEN="vk1.a.key", VK_GROUP_ID="236279991")
def test_check_bots_reports_no_telegram_connection_and_wrong_vk_group():
    import requests

    out = io.StringIO()
    with mock.patch("apps.bots.telegram_net.requests.request", side_effect=requests.ConnectTimeout("timeout")), \
            mock.patch("apps.bots.management.commands.check_bots.requests.post", side_effect=_vk_fake()):
        call_command("check_bots", stdout=out)
    text = out.getvalue()
    assert "Нет связи с Telegram" in text and "TELEGRAM_PROXY" in text
    assert "укажите VK_GROUP_ID=233702651" in text

"""Уведомления сотрудникам в группу Telegram и беседу ВК; боты в группах только подсказывают номер чата."""
from unittest import mock

import pytest
from django.test import override_settings

from apps.bots.adapters.telegram import group_chat_reply
from apps.bots.adapters.vk import VKBot, chat_reply
from apps.notifications.models import Notification
from apps.notifications.services import staff_recipient
from apps.notifications.tasks import send_notification_task, send_telegram


def test_telegram_group_reply_only_on_join_or_chatid():
    assert "TELEGRAM_STAFF_CHAT_ID=-100555" in group_chat_reply(-100555, None, [42], bot_id=42)
    assert "TELEGRAM_STAFF_CHAT_ID=-100555" in group_chat_reply(-100555, "/chatid@cvety_bot", [], bot_id=42)
    assert group_chat_reply(-100555, "Привет, кто сегодня на смене?", [], bot_id=42) is None
    assert group_chat_reply(-100555, None, [7], bot_id=42) is None  # добавили не бота, а человека


def test_vk_chat_reply_only_on_invite_or_chatid():
    invite = {"peer_id": 2000000003, "action": {"type": "chat_invite_user", "member_id": -233702651}}
    assert "VK_STAFF_PEER_ID=2000000003" in chat_reply(invite, "233702651")
    mention = {"peer_id": 2000000003, "text": "[club233702651|@flowersural878] /chatid"}
    assert "VK_STAFF_PEER_ID=2000000003" in chat_reply(mention, "233702651")
    assert chat_reply({"peer_id": 2000000003, "text": "заказ готов"}, "233702651") is None
    other = {"peer_id": 2000000003, "action": {"type": "chat_invite_user", "member_id": 777}}
    assert chat_reply(other, "233702651") is None


@override_settings(VK_GROUP_TOKEN="vk1.a.key", VK_GROUP_ID="233702651")
def test_vk_bot_does_not_sell_in_staff_chat():
    bot = VKBot()
    bot.api = mock.Mock()
    bot.engine = mock.Mock()
    bot.on_message({"peer_id": 2000000001, "from_id": 5, "text": "привет"})
    bot.engine.handle.assert_not_called()
    bot.api.call.assert_not_called()
    bot.on_message({"peer_id": 2000000001, "from_id": 5, "text": "",
                    "action": {"type": "chat_invite_user", "member_id": -233702651}})
    method = bot.api.call.call_args.args[0]
    assert method == "messages.send" and "VK_STAFF_PEER_ID=2000000001" in bot.api.call.call_args.kwargs["message"]
    bot.engine.handle.assert_not_called()


def _staff_notification():
    return Notification.objects.create(channel="staff", kind="staff_new_order", text="🆕 Новый заказ №1")


@pytest.mark.django_db
@override_settings(TELEGRAM_BOT_TOKEN="123:abc", TELEGRAM_STAFF_CHAT_ID="-100555",
                   VK_GROUP_TOKEN="vk1.a.key", VK_STAFF_PEER_ID="2000000001")
def test_staff_notification_goes_to_telegram_and_vk():
    assert staff_recipient() == "tg:-100555 vk:2000000001"
    n = _staff_notification()
    with mock.patch("apps.notifications.tasks.send_telegram") as tg, mock.patch("apps.notifications.tasks.send_vk") as vk:
        send_notification_task(n.id)
    assert tg.call_args.args[:2] == ("-100555", "🆕 Новый заказ №1")
    assert vk.call_args.args[:2] == ("2000000001", "🆕 Новый заказ №1")
    assert tg.call_count == vk.call_count == 1
    n.refresh_from_db()
    assert n.status == "sent" and n.error == ""


@pytest.mark.django_db
@override_settings(TELEGRAM_BOT_TOKEN="123:abc", TELEGRAM_STAFF_CHAT_ID="-100555",
                   VK_GROUP_TOKEN="vk1.a.key", VK_STAFF_PEER_ID="2000000001")
def test_staff_notification_one_channel_down_other_still_delivers():
    n = _staff_notification()
    with mock.patch("apps.notifications.tasks.send_telegram", side_effect=RuntimeError("timeout")), \
            mock.patch("apps.notifications.tasks.send_vk") as vk:
        send_notification_task(n.id)
    vk.assert_called_once()
    n.refresh_from_db()
    assert n.status == "sent" and "Telegram: timeout" in n.error


@pytest.mark.django_db
@override_settings(TELEGRAM_BOT_TOKEN="123:abc", TELEGRAM_STAFF_CHAT_ID="-100555", VK_STAFF_PEER_ID="")
def test_staff_notification_all_channels_down_is_failed():
    n = _staff_notification()
    with mock.patch("apps.notifications.tasks.send_telegram", side_effect=RuntimeError("timeout")):
        send_notification_task(n.id)
    n.refresh_from_db()
    assert n.status == "failed" and "Telegram: timeout" in n.error


@pytest.mark.django_db
@override_settings(TELEGRAM_BOT_TOKEN="", TELEGRAM_STAFF_CHAT_ID="", VK_GROUP_TOKEN="", VK_STAFF_PEER_ID="")
def test_staff_notification_without_chats_stays_in_admin_feed():
    n = _staff_notification()
    send_notification_task(n.id)
    n.refresh_from_db()
    assert n.status == "demo"


@override_settings(TELEGRAM_BOT_TOKEN="123:abc", TELEGRAM_PROXY="")
def test_telegram_group_upgraded_to_supergroup_uses_new_id():
    answers = [{"ok": False, "description": "group chat was upgraded", "parameters": {"migrate_to_chat_id": -100777}},
               {"ok": True}]
    with mock.patch("apps.notifications.tasks.telegram_net.call", side_effect=answers) as call:
        send_telegram("-555", "x")
    assert call.call_args_list[1].kwargs["json"]["chat_id"] == -100777

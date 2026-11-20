"""Интерфейс платёжного провайдера. Новые провайдеры (ЮKassa, CloudPayments, Т-Банк и т.п.)
реализуют этот интерфейс и регистрируются в registry.py — бизнес-логика заказов не меняется."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


class InvalidWebhook(Exception):
    """Подпись/данные не прошли проверку — отвечаем 400 (провайдер повторит уведомление)."""


class IgnoredWebhook(Exception):
    """Подлинное уведомление, которое не требует действий (промежуточный статус и т.п.) — отвечаем 200."""


@dataclass
class CreatedPayment:
    external_id: str
    confirmation_url: str


@dataclass
class WebhookEvent:
    event_id: str
    # payment.succeeded | payment.failed | payment.canceled | payment.expired | payment.chargeback
    # | refund.succeeded | refund.failed
    event_type: str
    external_id: str
    amount: int
    raw: dict


class PaymentProvider(ABC):
    code: str = ""
    title: str = ""
    is_test: bool = False
    # True — возврат не делается через API: сотрудник оформляет его в кабинете провайдера (см. refund_hint)
    manual_refunds: bool = False

    @abstractmethod
    def create_payment(self, payment, receipt: dict) -> CreatedPayment:
        """Создать платёж у провайдера и вернуть ссылку на оплату. receipt — данные чека по 54-ФЗ."""

    @abstractmethod
    def request_refund(self, payment, amount: int) -> None:
        """Запросить возврат. Итог приходит асинхронно через webhook (refund.succeeded / refund.failed)."""

    @abstractmethod
    def parse_webhook(self, body: bytes, headers: dict) -> WebhookEvent:
        """Проверить подпись/источник уведомления и разобрать его. При ошибке — InvalidWebhook."""

    def refund_hint(self, payment) -> str:
        """Подсказка сотруднику, как вернуть деньги, если manual_refunds=True."""
        return ""

    def fetch_event(self, payment) -> "WebhookEvent | None":
        """Запросить актуальный статус платежа у провайдера (сверка без уведомления). None — не поддерживается."""
        return None

    def telegram_invoice(self, payment) -> dict | None:
        """Точка расширения для встроенных счетов Telegram (Bot API sendInvoice) для физических товаров.
        Провайдер, поддерживающий Telegram Payments, возвращает параметры счёта (provider_token, prices,
        need_shipping_address и т.д.). По умолчанию None — бот отправляет защищённую ссылку на оплату."""
        return None


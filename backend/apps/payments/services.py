import json
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.errors import DomainError, NotFound

from .fiscal import build_receipt
from .models import Payment, PaymentWebhookEvent
from .providers.base import IgnoredWebhook, InvalidWebhook
from .providers.registry import get_provider

logger = logging.getLogger(__name__)


def _order_model():
    from apps.orders.models import Order

    return Order


def start_payment(order):
    """Создаёт новую попытку онлайн-оплаты (ссылка ведёт на страницу провайдера/симулятора)."""
    Order = _order_model()
    if order.status != Order.Status.AWAITING_PAYMENT:
        raise DomainError("Заказ не ожидает оплаты", code="invalid_state", http_status=409)
    order.payments.filter(status=Payment.Status.PENDING).update(status=Payment.Status.CANCELLED,
                                                                failure_reason="Создана новая попытка оплаты")
    provider = get_provider()
    receipt = build_receipt(order)
    payment = Payment.objects.create(order=order, provider=provider.code, amount=order.total, is_test=provider.is_test,
                                     receipt=receipt, expires_at=order.reservation_expires_at)
    try:
        created = provider.create_payment(payment, receipt)
    except RuntimeError as e:  # касса недоступна или не настроена — понятное сообщение вместо «ошибки сервера»
        logger.error("Не удалось создать платёж %s: %s", provider.code, e)
        raise DomainError("Онлайн-оплата сейчас недоступна. Попробуйте ещё раз через минуту",
                          code="payment_unavailable", http_status=503) from e
    payment.external_id = created.external_id
    payment.confirmation_url = created.confirmation_url
    payment.save(update_fields=["external_id", "confirmation_url"])
    order.payment_status = Order.PaymentStatus.PENDING
    order.save(update_fields=["payment_status", "updated_at"])
    return payment


def current_payment_url(order):
    p = order.payments.filter(status=Payment.Status.PENDING).order_by("-created_at").first()
    return p.confirmation_url if p else None


def ensure_payment_link(order):
    """Ссылка на оплату для заказа в статусе «Ожидает оплаты» (создаёт новую попытку при необходимости)."""
    Order = _order_model()
    if order.status != Order.Status.AWAITING_PAYMENT:
        return None
    url = current_payment_url(order)
    if url:
        return url
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        return start_payment(locked).confirmation_url


def process_webhook(provider_code, body: bytes, headers: dict):
    """Идемпотентная обработка уведомления. Повторное уведомление с тем же event_id игнорируется,
    а повторный успех по уже оплаченному платежу не меняет ни заказ, ни склад."""
    provider = get_provider(provider_code)
    try:
        event = provider.parse_webhook(body, headers)  # InvalidWebhook -> 400
    except IgnoredWebhook as e:
        return {"status": "ignored", "result": str(e)}
    return _process_event(provider, event)


def _process_event(provider, event):
    try:
        with transaction.atomic():
            log = PaymentWebhookEvent.objects.create(provider=provider.code, event_id=event.event_id,
                                                     event_type=event.event_type, payload=event.raw)
            result = _apply_event(event)
            log.result = result
            log.save(update_fields=["result"])
            return {"status": "processed", "result": result}
    except IntegrityError:
        return {"status": "duplicate", "result": "Уведомление уже обработано"}


def _apply_event(event):
    from apps.orders import services as orders

    Order = _order_model()
    payment = Payment.objects.select_for_update().filter(external_id=event.external_id).first()
    if not payment:
        return "Платёж не найден"
    order = Order.objects.select_for_update().get(pk=payment.order_id)
    t = event.event_type
    if t == "payment.succeeded":
        if payment.status in (Payment.Status.PAID, Payment.Status.REFUND_PENDING, Payment.Status.REFUNDED):
            return "Платёж уже учтён"
        if event.amount != payment.amount:
            payment.status = Payment.Status.FAILED
            payment.failure_reason = "Сумма в уведомлении не совпадает с суммой платежа"
            payment.save()
            return payment.failure_reason
        payment.status = Payment.Status.PAID
        payment.paid_at = timezone.now()
        payment.save()
        if order.status == Order.Status.AWAITING_PAYMENT:
            order.payment_status = Order.PaymentStatus.PAID
            order.save(update_fields=["payment_status", "updated_at"])
            orders._do_transition(order, Order.Status.CONFIRMED, actor_label="платёжная система",
                                  comment="Оплата получена (тестовый режим)" if payment.is_test else "Оплата получена")
            return "Заказ оплачен и подтверждён"
        if order.status == Order.Status.CANCELLED:
            # Оплата пришла после отмены (например, истёк резерв) — деньги нужно вернуть.
            order.payment_status = Order.PaymentStatus.PAID
            order.save(update_fields=["payment_status", "updated_at"])
            _refund(order, payment, actor_label="система", reason="Оплата поступила после отмены заказа")
            return "Оплата после отмены — инициирован возврат"
        order.payment_status = Order.PaymentStatus.PAID
        order.save(update_fields=["payment_status", "updated_at"])
        orders.log_event(order, "payment", "Оплата получена", actor_label="платёжная система")
        return "Оплата учтена"
    if t in ("payment.failed", "payment.canceled", "payment.expired"):
        if payment.status != Payment.Status.PENDING:
            return "Платёж уже закрыт"
        payment.status = Payment.Status.FAILED if t == "payment.failed" else Payment.Status.CANCELLED
        payment.failure_reason = {"payment.failed": "Ошибка оплаты", "payment.expired": "Истёк срок оплаты"}.get(
            t, "Покупатель отменил оплату")
        payment.save()
        if order.payment_status == Order.PaymentStatus.PENDING:
            order.payment_status = Order.PaymentStatus.FAILED
            order.save(update_fields=["payment_status", "updated_at"])
        orders.log_event(order, "payment", payment.failure_reason, actor_label="платёжная система")
        return payment.failure_reason
    if t in ("refund.succeeded", "payment.chargeback"):
        if payment.status == Payment.Status.REFUNDED:
            return "Возврат уже учтён"
        if payment.status not in (Payment.Status.PAID, Payment.Status.REFUND_PENDING):
            return "Платёж не был оплачен — возвращать нечего"
        payment.status = Payment.Status.REFUNDED
        payment.refunded_amount = payment.amount
        payment.save()
        order.payment_status = Order.PaymentStatus.REFUNDED
        order.save(update_fields=["payment_status", "updated_at"])
        msg = ("Банк отозвал оплату (chargeback): деньги вернулись покупателю — проверьте заказ"
               if t == "payment.chargeback" else "Возврат выполнен")
        orders.log_event(order, "payment", msg, actor_label="платёжная система")
        return msg
    if t == "refund.failed":
        orders.log_event(order, "payment", "Ошибка возврата — требуется ручная проверка", actor_label="платёжная система")
        return "Ошибка возврата"
    return "Неизвестный тип уведомления"


def _refund(order, payment, *, user=None, actor_label="", reason=""):
    from apps.orders import services as orders

    Order = _order_model()
    payment.status = Payment.Status.REFUND_PENDING
    payment.save(update_fields=["status", "updated_at"])
    order.payment_status = Order.PaymentStatus.REFUND_PENDING
    order.save(update_fields=["payment_status", "updated_at"])
    provider = get_provider(payment.provider)
    provider.request_refund(payment, payment.amount)
    orders.log_event(order, "payment", f"Запрошен возврат: {reason}".strip(), actor=user, actor_label=actor_label)
    if provider.manual_refunds:
        if payment.is_test:  # тестовый платёж: деньги не списывались — закрываем возврат сразу
            payment.status = Payment.Status.REFUNDED
            payment.refunded_amount = payment.amount
            payment.save(update_fields=["status", "refunded_amount", "updated_at"])
            order.payment_status = Order.PaymentStatus.REFUNDED
            order.save(update_fields=["payment_status", "updated_at"])
        orders.log_event(order, "payment", provider.refund_hint(payment), actor=user, actor_label=actor_label)


def refund_order(order_id, user, reason=""):
    Order = _order_model()
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        payment = order.payments.select_for_update().filter(status=Payment.Status.PAID).exclude(
            provider__in=["cash_on_delivery", "store_cash", "store_card"]).first()
        if not payment:
            raise DomainError("Нет онлайн-платежа, который можно вернуть", code="no_refundable_payment",
                              http_status=409)
        _refund(order, payment, user=user, reason=reason or "по решению сотрудника")
        return order


def on_order_cancelled(order):
    """Вызывается внутри транзакции отмены заказа."""
    Order = _order_model()
    order.payments.filter(status=Payment.Status.PENDING).update(status=Payment.Status.CANCELLED,
                                                                failure_reason="Заказ отменён")
    paid = order.payments.filter(status=Payment.Status.PAID).exclude(
        provider__in=["cash_on_delivery", "store_cash", "store_card"]).first()
    if paid:
        _refund(order, paid, actor_label="система", reason="заказ отменён")
    elif order.payment_status in (Order.PaymentStatus.PENDING, Order.PaymentStatus.FAILED):
        order.payment_status = Order.PaymentStatus.UNPAID
        order.save(update_fields=["payment_status", "updated_at"])


def sync_pending(order, *, min_interval=20):
    """Сверяет неоплаченные попытки заказа с провайдером (если он это умеет). Нужна, когда покупатель вернулся
    с формы оплаты раньше уведомления или уведомление не дошло. Не чаще раза в min_interval секунд на заказ."""
    from django.core.cache import cache

    Order = _order_model()
    if order.status != Order.Status.AWAITING_PAYMENT:
        return None
    pending = list(order.payments.filter(status=Payment.Status.PENDING).exclude(external_id=None)
                   .exclude(external_id="").order_by("-created_at")[:3])
    if not pending or (min_interval and not cache.add(f"pay-sync:{order.pk}", 1, min_interval)):
        return None
    done = None
    for p in pending:
        try:
            provider = get_provider(p.provider)
        except RuntimeError:
            continue
        event = provider.fetch_event(p)
        if event:
            done = _process_event(provider, event)
    return done


# ---- Симулятор: действия на тестовой странице оплаты

SIM_ACTIONS = {
    "succeed": ("payment.succeeded", {Payment.Status.PENDING}),
    "fail": ("payment.failed", {Payment.Status.PENDING}),
    "cancel": ("payment.canceled", {Payment.Status.PENDING}),
    "refund_succeed": ("refund.succeeded", {Payment.Status.REFUND_PENDING}),
    "refund_fail": ("refund.failed", {Payment.Status.REFUND_PENDING}),
}


def get_by_token(token):
    payment = Payment.objects.select_related("order").filter(token=token).first()
    if not payment:
        raise NotFound("Платёж не найден")
    return payment


def simulator_action(token, action):
    payment = get_by_token(token)
    if payment.provider != "simulator":
        raise DomainError("Это не тестовый платёж", code="not_simulator", http_status=400)
    if action not in SIM_ACTIONS:
        raise DomainError("Неизвестное действие", code="bad_action")
    event_type, allowed = SIM_ACTIONS[action]
    if payment.status not in allowed:
        raise DomainError(f"Действие недоступно: платёж в статусе «{payment.get_status_display()}»",
                          code="invalid_state", http_status=409)
    provider = get_provider("simulator")
    body, headers = provider.build_event(payment, event_type)
    return process_webhook("simulator", body, headers)

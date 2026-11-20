"""Резервы: истечение неоплаченных, защита подтверждённых, отмены."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.orders import services as orders
from apps.orders.models import Order
from apps.reservations.models import StockReservation

pytestmark = pytest.mark.django_db
S = Order.Status


def test_expired_unpaid_online_reservation_is_released(shop):
    """5. Неоплаченный онлайн-заказ после истечения резерва освобождает товар."""
    b = shop.bouquet(assembled=1)
    order = shop.place((b, 1))
    assert order.status == S.AWAITING_PAYMENT and order.reservation_expires_at
    assert shop.available(b) == 0
    # до истечения ничего не происходит
    assert orders.expire_overdue_orders() == []
    # через 16 минут резерв истёк
    assert orders.expire_overdue_orders(now=timezone.now() + timedelta(minutes=16)) == [order.pk]
    order.refresh_from_db()
    assert order.status == S.CANCELLED and order.cancel_reason == "Истёк срок резерва"
    assert shop.available(b) == 1
    assert shop.balance(b.inventory_item).reserved == 0
    assert order.reservations.get().status == StockReservation.Status.EXPIRED
    assert order.payments.get().status == "cancelled"  # ссылка на оплату больше не действует


def test_confirmed_cod_order_not_cancelled_by_timer(shop, staff):
    """6. Подтверждённый заказ с оплатой при получении не отменяется по таймеру."""
    b = shop.bouquet(assembled=1)
    order = shop.place((b, 1), payment="on_delivery")
    assert order.status == S.NEW and order.reservation_expires_at  # ждёт подтверждения магазина
    order = orders.staff_confirm(order.id, staff["florist"])
    assert order.status == S.CONFIRMED and order.reservation_expires_at is None
    assert orders.expire_overdue_orders(now=timezone.now() + timedelta(days=3)) == []
    order.refresh_from_db()
    assert order.status == S.CONFIRMED
    assert shop.balance(b.inventory_item).reserved == 1


def test_unconfirmed_cod_order_expires_after_hold(shop):
    b = shop.bouquet(assembled=1)
    order = shop.place((b, 1), payment="on_delivery")
    assert orders.expire_overdue_orders(now=timezone.now() + timedelta(hours=4)) == [order.pk]
    assert shop.available(b) == 1


def test_paid_order_is_never_expired(shop):
    from apps.payments import services as payments

    b = shop.bouquet(assembled=1)
    order = shop.place((b, 1))
    payments.simulator_action(order.payments.get().token, "succeed")
    order.refresh_from_db()
    assert order.status == S.CONFIRMED
    assert orders.expire_overdue_orders(now=timezone.now() + timedelta(days=1)) == []


def test_cancel_before_assembly_releases_reservation(shop, staff):
    """10. Отмена до сборки — резерв снят, остаток снова доступен."""
    b = shop.bouquet(assembled=2)
    order = shop.place((b, 2), payment="on_delivery")
    orders.staff_confirm(order.id, staff["florist"])
    orders.cancel(order.id, user=staff["florist"], reason="Клиент передумал")
    bal = shop.balance(b.inventory_item)
    assert (bal.quantity, bal.reserved) == (2, 0)
    assert set(order.reservations.values_list("status", flat=True)) == {"released"}


def test_cancel_after_ready_returns_finished_bouquet(shop, staff):
    """10. Отмена после сборки: готовый букет возвращается на склад (без двойного учёта)."""
    b = shop.bouquet(assembled=1)
    order = shop.place((b, 1), payment="on_delivery")
    orders.staff_confirm(order.id, staff["florist"])
    orders.transition(order.id, S.ASSEMBLING, user=staff["florist"])
    orders.transition(order.id, S.READY, user=staff["florist"])
    bal = shop.balance(b.inventory_item)
    assert (bal.quantity, bal.reserved) == (0, 0)  # списан при готовности
    orders.cancel(order.id, user=staff["owner"], reason="Не дозвонились")
    bal.refresh_from_db()
    assert (bal.quantity, bal.reserved) == (1, 0)
    assert shop.available(b) == 1


def test_cancel_after_ready_made_to_order_bouquet_goes_to_stock(shop, staff):
    """Букет, собранный под заказ по рецептуре, после отмены становится готовым букетом в наличии."""
    b = shop.bouquet(made_to_order=True, roses=3)
    rose_before = shop.balance(shop.rose).quantity
    order = shop.place((b, 1), payment="on_delivery")
    orders.staff_confirm(order.id, staff["florist"])
    orders.transition(order.id, S.ASSEMBLING, user=staff["florist"])
    orders.transition(order.id, S.READY, user=staff["florist"])
    assert shop.balance(shop.rose).quantity == rose_before - 3
    orders.cancel(order.id, user=staff["owner"])
    assert shop.balance(shop.rose).quantity == rose_before - 3  # цветы уже в букете
    assert shop.balance(b.inventory_item).quantity == 1  # готовый букет можно продать


def test_cancel_after_ready_custom_bouquet_warns(shop, staff):
    """Индивидуальный букет после сборки не возвращается — материалы уже использованы, есть предупреждение."""
    from apps.payments import services as payments

    order = shop.place(custom=shop.custom_composition(roses=5))  # индивидуальный букет — только онлайн-оплата
    assert order.status == S.AWAITING_CONFIRMATION
    orders.staff_confirm(order.id, staff["florist"])
    order.refresh_from_db()
    assert order.status == S.AWAITING_PAYMENT
    payments.ensure_payment_link(order)
    payments.simulator_action(order.payments.order_by("-id").first().token, "succeed")
    orders.transition(order.id, S.ASSEMBLING, user=staff["florist"])
    orders.transition(order.id, S.READY, user=staff["florist"])
    rose = shop.balance(shop.rose).quantity
    orders.cancel(order.id, user=staff["owner"])
    assert shop.balance(shop.rose).quantity == rose
    ev = order.events.filter(to_status=S.CANCELLED).get()
    assert "не возвращаются" in ev.message


def test_preorder_does_not_reserve_until_assembly(shop, staff):
    b = shop.bouquet(made_to_order=True)
    order = shop.place((b, 1), days=10, payment="on_delivery")
    assert order.is_preorder and order.status == S.AWAITING_CONFIRMATION
    assert not order.reservations.exists()
    assert shop.balance(shop.rose).reserved == 0
    orders.staff_confirm(order.id, staff["florist"])
    orders.transition(order.id, S.ASSEMBLING, user=staff["florist"])
    orders.transition(order.id, S.READY, user=staff["florist"])
    assert order.reservations.filter(status="consumed").exists()


def test_invalid_transition_rejected(shop, staff):
    b = shop.bouquet(assembled=1)
    order = shop.place((b, 1))
    with pytest.raises(Exception) as e:
        orders.transition(order.id, S.CONFIRMED, user=staff["florist"])  # онлайн-заказ без оплаты
    assert getattr(e.value, "code", "") == "payment_required"
    with pytest.raises(Exception) as e:
        orders.transition(order.id, S.DELIVERED, user=staff["florist"])
    assert getattr(e.value, "code", "") == "invalid_transition"

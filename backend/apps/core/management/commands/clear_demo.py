"""Удаляет демо-заказы и демо-покупателей перед запуском магазина для настоящих покупателей.

    docker compose exec backend python manage.py clear_demo            # показать, что будет удалено
    docker compose exec backend python manage.py clear_demo --yes      # удалить
    docker compose exec backend python manage.py clear_demo --yes --catalog   # + снять с продажи демо-товары

Резервы демо-заказов снимаются (цветы возвращаются в «доступно»), складские движения остаются в журнале
без ссылки на заказ. Настоящие заказы не трогаются: демо — это заказы демо-покупателей и всё, что создала
команда seed_demo при первом запуске.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Max, Min, Q

from apps.catalog.models import Product
from apps.core.models import User
from apps.customers.models import Customer
from apps.notifications.models import Notification
from apps.orders.models import Order, OrderEvent
from apps.reservations import services as reservations


def demo_orders():
    q = Q(is_demo=True) | Q(customer__is_demo=True)
    span = Customer.objects.filter(is_demo=True).aggregate(a=Min("created_at"), b=Max("created_at"))
    if span["a"]:
        # всё, что создано во время заполнения демо-данными (включая продажи в магазине без покупателя)
        ids = OrderEvent.objects.filter(event_type="created", created_at__gte=span["a"] - timedelta(minutes=2),
                                        created_at__lte=span["b"] + timedelta(minutes=15)).values("order_id")
        q |= Q(pk__in=ids)
    q |= Q(pk__in=OrderEvent.objects.filter(event_type="created", actor_label="демо").values("order_id"))
    return Order.objects.filter(q).distinct()


class Command(BaseCommand):
    help = "Удалить демо-заказы и демо-покупателей (без --yes только показывает, что будет удалено)"

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Подтвердить удаление")
        parser.add_argument("--catalog", action="store_true", help="Также снять с продажи демо-товары")

    def handle(self, *args, yes=False, catalog=False, **opts):
        orders = demo_orders()
        customers = Customer.objects.filter(is_demo=True)
        staff = User.objects.filter(is_demo=True).exclude(role=User.Role.OWNER)
        products = Product.objects.filter(is_demo=True, is_active=True) if catalog else Product.objects.none()
        self.stdout.write(f"Демо-заказов: {orders.count()}, демо-покупателей: {customers.count()}, "
                          f"демо-сотрудников: {staff.count()}" + (f", демо-товаров к скрытию: {products.count()}" if catalog else ""))
        if not yes:
            self.stdout.write(self.style.WARNING("Ничего не удалено. Чтобы удалить, добавьте --yes"))
            return
        with transaction.atomic():
            ids = list(orders.values_list("pk", flat=True))
            for o in Order.objects.select_for_update().filter(pk__in=ids):
                reservations.release(o)
            Notification.objects.filter(order_id__in=ids).delete()
            n_orders = Order.objects.filter(pk__in=ids).delete()[0] if ids else 0
            left = customers.exclude(orders__isnull=False)
            n_cust = left.count()
            left.delete()
            n_staff = staff.count()
            staff.delete()
            n_prod = products.update(is_active=False) if catalog else 0
        self.stdout.write(self.style.SUCCESS(
            f"Удалено: заказов {len(ids)} (записей {n_orders}), покупателей {n_cust}, сотрудников {n_staff}"
            + (f"; скрыто товаров {n_prod}" if catalog else "") + "."))

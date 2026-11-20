"""Резервирование остатков под заказы. Вызывается только внутри транзакции оформления/смены статуса заказа."""
from collections import defaultdict

from django.utils import timezone

from apps.catalog import builder
from apps.catalog.models import Product
from apps.inventory.models import StockMovement
from apps.inventory.services import InsufficientStock, add_stock, consume_reserved, lock_balances

from .models import StockReservation

R = StockReservation


def _recipe_components(product):
    recipe = getattr(product.inventory_item, "recipe", None)
    if not recipe or not recipe.is_active:
        return []
    return [(c.item_id, c.quantity) for c in recipe.components.all()]


def plan(lines):
    """Строит план резервирования под блокировкой строк остатков.

    lines: [{"key", "type": "product"|"custom_bouquet", "product": Product|None, "composition": dict|None, "quantity"}]
    Возвращает (plans, reservations, balances):
      plans[key] = {"stock": n, "made_to_order": m} или {"custom": n}
      reservations = [(key, item_id, qty, kind)]
    Бросает InsufficientStock, если нельзя зарезервировать.
    """
    ids = set()
    for ln in lines:
        if ln["type"] == "custom_bouquet":
            ids |= set(builder.material_lines(ln["composition"]).keys())
        else:
            p = ln["product"]
            ids.add(p.inventory_item_id)
            if p.type == Product.Type.BOUQUET and p.allow_made_to_order:
                ids |= {i for i, _ in _recipe_components(p)}
    balances = lock_balances(ids)
    free = {i: b.available for i, b in balances.items()}
    plans, reservations = {}, []

    def take(key, item_id, qty, kind):
        if free[item_id] < qty:
            raise InsufficientStock(balances[item_id].item, qty, free[item_id])
        free[item_id] -= qty
        reservations.append((key, item_id, qty, kind))

    for ln in lines:
        key, qty = ln["key"], ln["quantity"]
        if ln["type"] == "custom_bouquet":
            for item_id, per in builder.material_lines(ln["composition"]).items():
                take(key, item_id, per * qty, R.Kind.COMPONENT)
            plans[key] = {"custom": qty}
            continue
        p = ln["product"]
        stock_qty = min(max(free[p.inventory_item_id], 0), qty)
        rest = qty - stock_qty
        if rest and p.type == Product.Type.BOUQUET and p.allow_made_to_order:
            comps = _recipe_components(p)
            if comps:
                if any(free[i] < per * rest for i, per in comps):
                    can = min(free[i] // per for i, per in comps)
                    raise InsufficientStock(p.inventory_item, qty, stock_qty + max(can, 0))
                for item_id, per in comps:
                    take(key, item_id, per * rest, R.Kind.COMPONENT)
                if stock_qty:
                    take(key, p.inventory_item_id, stock_qty, R.Kind.FINISHED)
                plans[key] = {"stock": stock_qty, "made_to_order": rest}
                continue
        if rest:
            raise InsufficientStock(p.inventory_item, qty, stock_qty)
        take(key, p.inventory_item_id, qty, R.Kind.FINISHED)
        plans[key] = {"stock": qty, "made_to_order": 0}
    return plans, reservations, balances


def apply(order, reservations, balances, item_by_key, expires_at=None):
    """Записывает резервы: увеличивает reserved в stock_balances и создаёт строки stock_reservations."""
    per_item = defaultdict(int)
    rows = []
    for key, item_id, qty, kind in reservations:
        per_item[item_id] += qty
        rows.append(R(order=order, order_item=item_by_key.get(key), item_id=item_id, quantity=qty, kind=kind,
                      expires_at=expires_at))
    for item_id, qty in per_item.items():
        bal = balances[item_id]
        bal.reserved += qty
        if bal.reserved > bal.quantity:  # защитная проверка; дополнительно действует CHECK в БД
            raise InsufficientStock(bal.item, qty, bal.quantity - bal.reserved + qty)
        bal.save(update_fields=["reserved", "updated_at"])
    R.objects.bulk_create(rows)
    return rows


def set_expiry(order, expires_at):
    order.reservations.filter(status=R.Status.ACTIVE).update(expires_at=expires_at)


def release(order, status=R.Status.RELEASED):
    active = list(order.reservations.select_for_update().filter(status=R.Status.ACTIVE))
    if not active:
        return 0
    balances = lock_balances([r.item_id for r in active])
    per_item = defaultdict(int)
    for r in active:
        per_item[r.item_id] += r.quantity
    for item_id, qty in per_item.items():
        bal = balances[item_id]
        bal.reserved = max(bal.reserved - qty, 0)
        bal.save(update_fields=["reserved", "updated_at"])
    R.objects.filter(pk__in=[r.pk for r in active]).update(status=status, closed_at=timezone.now())
    return len(active)


def consume(order, user=None):
    """Фактическое списание зарезервированного при сборке/выдаче заказа."""
    active = list(order.reservations.select_for_update().filter(status=R.Status.ACTIVE).select_related("item"))
    balances = lock_balances([r.item_id for r in active])
    for r in active:
        mtype = StockMovement.Type.ORDER_FULFILLMENT if r.kind == R.Kind.FINISHED else StockMovement.Type.ASSEMBLY_CONSUME
        consume_reserved(balances[r.item_id], r.quantity, mtype, order=order, user=user,
                         reason=f"Заказ №{order.number}")
    R.objects.filter(pk__in=[r.pk for r in active]).update(status=R.Status.CONSUMED, closed_at=timezone.now())
    return active


def return_finished(order, user=None):
    """При отмене после сборки возвращает на склад то, что можно продать повторно:
    готовые букеты из запаса, цветы, доп. товары и букеты, собранные под заказ по рецептуре.
    Индивидуальные букеты (конструктор) вернуть как товар нельзя — возвращается флаг для ручного списания."""
    consumed = list(order.reservations.filter(status=R.Status.CONSUMED, kind=R.Kind.FINISHED))
    made_to_order = []
    for oi in order.items.filter(item_type="product").exclude(inventory_item=None):
        n = int((oi.fulfillment_plan or {}).get("made_to_order") or 0)
        if n and order.reservations.filter(order_item=oi, status=R.Status.CONSUMED, kind=R.Kind.COMPONENT).exists():
            made_to_order.append((oi.inventory_item_id, n))
    balances = lock_balances([r.item_id for r in consumed] + [i for i, _ in made_to_order])
    for r in consumed:
        add_stock(balances[r.item_id], r.quantity, StockMovement.Type.RETURN, order=order, user=user,
                  reason=f"Отмена заказа №{order.number}")
    for item_id, n in made_to_order:
        add_stock(balances[item_id], n, StockMovement.Type.RETURN, order=order, user=user,
                  reason=f"Отмена заказа №{order.number}: собранный букет возвращён в продажу")
    has_custom = order.reservations.filter(status=R.Status.CONSUMED, kind=R.Kind.COMPONENT,
                                           order_item__item_type="custom_bouquet").exists()
    return len(consumed) + len(made_to_order), has_custom

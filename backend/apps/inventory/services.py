"""Складские операции. Все изменения остатков — в транзакции с блокировкой строк stock_balances
(SELECT ... FOR UPDATE, в порядке возрастания id — чтобы исключить взаимоблокировки)."""
import uuid
from dataclasses import dataclass

from django.db import transaction

from apps.core.errors import DomainError, ValidationError

from .models import MAIN_LOCATION, InventoryItem, StockBalance, StockMovement

T = StockMovement.Type


class InsufficientStock(DomainError):
    code = "insufficient_stock"
    http_status = 409

    def __init__(self, item, requested, available):
        self.item, self.requested, self.available = item, requested, available
        super().__init__(
            f"Недостаточно товара «{item.name}»: запрошено {requested}, доступно {max(available, 0)}",
            details={"item_id": item.id, "requested": requested, "available": max(available, 0)},
        )


def ensure_balance(item, location=MAIN_LOCATION):
    bal, _ = StockBalance.objects.get_or_create(item=item, location=location)
    return bal


def lock_balances(item_ids, location=MAIN_LOCATION):
    """Блокирует строки остатков. Вызывать только внутри transaction.atomic()."""
    ids = sorted(set(int(i) for i in item_ids))
    if not ids:
        return {}
    existing = set(StockBalance.objects.filter(item_id__in=ids, location=location).values_list("item_id", flat=True))
    for missing in set(ids) - existing:
        StockBalance.objects.get_or_create(item_id=missing, location=location)
    rows = StockBalance.objects.select_for_update().filter(item_id__in=ids, location=location).order_by("item_id")
    return {b.item_id: b for b in rows.select_related("item")}


def availability_map(item_ids=None, location=MAIN_LOCATION):
    qs = StockBalance.objects.filter(location=location)
    if item_ids is not None:
        qs = qs.filter(item_id__in=list(item_ids))
    return {b["item_id"]: b["quantity"] - b["reserved"] for b in qs.values("item_id", "quantity", "reserved")}


def _move(balance, delta, movement_type, *, user=None, order=None, reason="", unit_cost=None, batch_id=None,
          consume_reserved=0):
    """Применяет изменение к заблокированному остатку и пишет движение."""
    if delta == 0:
        return None
    if delta < 0:
        free = balance.quantity - balance.reserved + consume_reserved
        if -delta > free:
            raise InsufficientStock(balance.item, -delta, free)
    balance.quantity += delta
    balance.reserved -= consume_reserved
    balance.save(update_fields=["quantity", "reserved", "updated_at"])
    return StockMovement.objects.create(
        item=balance.item,
        location=balance.location,
        movement_type=movement_type,
        quantity_delta=delta,
        balance_after=balance.quantity,
        unit_cost=unit_cost,
        reason=reason[:255],
        order=order,
        user=user,
        batch_id=batch_id or uuid.uuid4(),
    )


@dataclass
class SupplyLine:
    item_id: int
    quantity: int
    unit_cost: int | None = None


def _positive(qty, label="Количество"):
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        raise ValidationError(f"{label}: ожидается целое число")
    if qty <= 0:
        raise ValidationError(f"{label} должно быть больше нуля")
    return qty


@transaction.atomic
def receive_supply(lines, user=None, reason="Поставка"):
    batch = uuid.uuid4()
    if not lines:
        raise ValidationError("Добавьте хотя бы одну позицию поставки")
    balances = lock_balances([l.item_id for l in lines])
    moves = []
    for line in lines:
        qty = _positive(line.quantity)
        bal = balances[int(line.item_id)]
        moves.append(_move(bal, qty, T.SUPPLY, user=user, reason=reason, unit_cost=line.unit_cost, batch_id=batch))
        if line.unit_cost:
            InventoryItem.objects.filter(pk=bal.item_id).update(purchase_price=int(line.unit_cost))
    return moves


@transaction.atomic
def write_off(item_id, quantity, reason, user=None):
    if not (reason or "").strip():
        raise ValidationError("Укажите причину списания")
    qty = _positive(quantity)
    bal = lock_balances([item_id])[int(item_id)]
    if qty > bal.available:
        raise DomainError(
            f"Нельзя списать {qty}: свободно {bal.available} (остальное в резерве под заказы)",
            code="insufficient_stock", http_status=409,
        )
    return _move(bal, -qty, T.WRITE_OFF, user=user, reason=reason)


@transaction.atomic
def adjust(item_id, delta, reason, user=None):
    if not (reason or "").strip():
        raise ValidationError("Укажите причину корректировки")
    delta = int(delta)
    if delta == 0:
        raise ValidationError("Изменение не может быть нулевым")
    bal = lock_balances([item_id])[int(item_id)]
    return _move(bal, delta, T.ADJUSTMENT, user=user, reason=reason)


@transaction.atomic
def inventory_count(counts, user=None, reason="Инвентаризация"):
    """counts: {item_id: фактически пересчитано}. Пишет движения на разницу."""
    batch = uuid.uuid4()
    balances = lock_balances(counts.keys())
    result = []
    for item_id, counted in counts.items():
        counted = int(counted)
        if counted < 0:
            raise ValidationError("Количество не может быть отрицательным")
        bal = balances[int(item_id)]
        if counted < bal.reserved:
            raise DomainError(
                f"«{bal.item.name}»: пересчитано {counted}, но {bal.reserved} уже в резерве под заказы. "
                "Сначала отмените или перенесите заказы.",
                code="reserved_conflict", http_status=409,
            )
        delta = counted - bal.quantity
        mv = _move(bal, delta, T.INVENTORY, user=user, reason=reason, batch_id=batch) if delta else None
        result.append({"item_id": bal.item_id, "before": counted - delta, "after": counted, "delta": delta, "movement": mv})
    return result


def consume_free(balance, qty, movement_type, *, order=None, user=None, reason="", batch_id=None):
    """Списание из свободного остатка (продажа в магазине, сборка). Остаток должен быть заблокирован."""
    return _move(balance, -qty, movement_type, order=order, user=user, reason=reason, batch_id=batch_id)


def consume_reserved(balance, qty, movement_type, *, order=None, user=None, reason="", batch_id=None):
    """Списание ранее зарезервированного количества."""
    return _move(balance, -qty, movement_type, order=order, user=user, reason=reason, batch_id=batch_id,
                 consume_reserved=qty)


def add_stock(balance, qty, movement_type, *, order=None, user=None, reason="", batch_id=None):
    return _move(balance, qty, movement_type, order=order, user=user, reason=reason, batch_id=batch_id)

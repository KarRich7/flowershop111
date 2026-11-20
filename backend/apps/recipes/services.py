import uuid

from django.db import transaction

from apps.core.errors import ValidationError
from apps.inventory.models import InventoryItem, StockMovement
from apps.inventory.services import InsufficientStock, add_stock, availability_map, consume_free, lock_balances

from .models import BouquetRecipe, RecipeComponent


def components_of(recipe):
    return [(c.item_id, c.quantity) for c in recipe.components.all()]


def capacity(recipe, avail=None):
    """Сколько букетов можно собрать из свободных остатков."""
    comps = components_of(recipe)
    if not comps:
        return 0
    avail = avail if avail is not None else availability_map([i for i, _ in comps])
    return max(0, min(avail.get(i, 0) // q for i, q in comps))


def cost(recipe):
    return sum(c.item.purchase_price * c.quantity for c in recipe.components.select_related("item"))


@transaction.atomic
def assemble(recipe, count, user=None):
    """Заблаговременная сборка готовых букетов: компоненты списываются сейчас, готовый букет приходуется.
    При продаже такого букета повторно компоненты не списываются."""
    count = int(count)
    if count <= 0:
        raise ValidationError("Количество должно быть больше нуля")
    comps = components_of(recipe)
    if not comps:
        raise ValidationError("У рецептуры нет компонентов")
    balances = lock_balances([i for i, _ in comps] + [recipe.bouquet_item_id])
    for item_id, qty in comps:
        need = qty * count
        if balances[item_id].available < need:
            raise InsufficientStock(balances[item_id].item, need, balances[item_id].available)
    batch = uuid.uuid4()
    reason = f"Сборка {count} шт. «{recipe.bouquet_item.name}»"
    for item_id, qty in comps:
        consume_free(balances[item_id], qty * count, StockMovement.Type.ASSEMBLY_CONSUME, user=user, reason=reason,
                     batch_id=batch)
    return add_stock(balances[recipe.bouquet_item_id], count, StockMovement.Type.ASSEMBLY_PRODUCE, user=user,
                     reason=reason, batch_id=batch)


@transaction.atomic
def set_components(recipe, components):
    """components: [{item_id, quantity}]"""
    seen = {}
    for c in components:
        item_id, qty = int(c["item_id"]), int(c["quantity"])
        if qty <= 0:
            raise ValidationError("Количество компонента должно быть больше нуля")
        if item_id == recipe.bouquet_item_id:
            raise ValidationError("Букет не может входить в собственную рецептуру")
        seen[item_id] = seen.get(item_id, 0) + qty
    items = InventoryItem.objects.filter(id__in=seen.keys()).exclude(category=InventoryItem.Category.BOUQUET)
    if items.count() != len(seen):
        raise ValidationError("Компонентами могут быть только материалы (не готовые букеты)")
    recipe.components.all().delete()
    RecipeComponent.objects.bulk_create([RecipeComponent(recipe=recipe, item_id=i, quantity=q) for i, q in seen.items()])
    recipe.save(update_fields=["updated_at"])
    return recipe


def get_or_create_recipe(bouquet_item):
    recipe, _ = BouquetRecipe.objects.get_or_create(bouquet_item=bouquet_item)
    return recipe

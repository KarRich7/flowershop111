"""Конструктор индивидуального букета (только сайт). Стоимость считается на сервере по актуальным ценам."""
from collections import defaultdict

from apps.core.errors import ValidationError
from apps.core.models import MAX_CUSTOM_STEMS_LIMIT, ShopSettings
from apps.inventory.models import InventoryItem
from apps.inventory.services import availability_map

C = InventoryItem.Category


def _qty(v):
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise ValidationError("Количество должно быть целым числом")
    if v <= 0:
        raise ValidationError("Количество должно быть больше нуля")
    return v


def normalize_composition(data):
    data = data or {}
    norm = {
        "flowers": [{"item_id": int(x["item_id"]), "quantity": _qty(x.get("quantity", 1))} for x in data.get("flowers") or []],
        "greenery": [{"item_id": int(x["item_id"]), "quantity": _qty(x.get("quantity", 1))} for x in data.get("greenery") or []],
        "packaging_id": int(data["packaging_id"]) if data.get("packaging_id") else None,
        "ribbon_id": int(data["ribbon_id"]) if data.get("ribbon_id") else None,
        "card_id": int(data["card_id"]) if data.get("card_id") else None,
        "card_text": (data.get("card_text") or "").strip()[:300],
        "wishes": (data.get("wishes") or "").strip()[:500],
        # «Конструктор по фото»: покупатель выбрал только цветы, упаковку и ленту — форму и расстановку
        # флорист делает на своё усмотрение, эскиза нет
        "florist_choice": data.get("florist_choice") in (True, 1, "1", "true"),
    }
    norm["layout"] = [] if norm["florist_choice"] else _layout(data.get("layout"), norm)
    return norm


def _layout(raw, norm):
    """Расположение стеблей из конструктора: [{item_id, x, y, r, f}], x/y — доли 0..1 внутри букета,
    r — поворот в градусах, f — цветок отражён зеркально.
    На цену не влияет; сохраняется в заказе, чтобы флорист видел эскиз."""
    if not isinstance(raw, list):
        return []
    limits = defaultdict(int)
    for row in norm["flowers"] + norm["greenery"]:
        limits[row["item_id"]] += row["quantity"]
    out, used = [], defaultdict(int)
    for p in raw[:400]:
        try:
            item_id, x, y = int(p["item_id"]), float(p["x"]), float(p["y"])
            r = float(p.get("r") or 0)
            flip = p.get("f") in (True, 1, "1", "true")
        except (TypeError, ValueError, KeyError):
            continue
        if used[item_id] >= limits.get(item_id, 0):
            continue
        used[item_id] += 1
        if x != x or y != y:  # NaN
            continue
        if r != r:
            r = 0.0
        row = {"item_id": item_id, "x": round(min(max(x, 0.0), 1.0), 4), "y": round(min(max(y, 0.0), 1.0), 4),
               "r": round(max(min(r, 180.0), -180.0), 1)}
        if flip:
            row["f"] = True
        out.append(row)
    return out


def material_lines(comp):
    """Список (item_id, qty) всех материалов индивидуального букета (на 1 букет)."""
    lines = defaultdict(int)
    for row in comp["flowers"] + comp["greenery"]:
        lines[row["item_id"]] += row["quantity"]
    for key in ("packaging_id", "ribbon_id", "card_id"):
        if comp.get(key):
            lines[comp[key]] += 1
    return dict(lines)


def quote(data, quantity=1, check_stock=True, extra_demand=None):
    """Проверяет состав и рассчитывает цену. Возвращает dict с позициями, суммами и нормализованным составом."""
    comp = normalize_composition(data)
    settings = ShopSettings.load()
    if not comp["flowers"]:
        raise ValidationError("Добавьте в букет хотя бы один вид цветов", code="empty_bouquet")
    stems = sum(r["quantity"] for r in comp["flowers"])
    if stems < settings.min_custom_stems:
        raise ValidationError(f"Минимум {settings.min_custom_stems} цветка в букете", code="too_few_stems")
    max_stems = min(settings.max_custom_stems, MAX_CUSTOM_STEMS_LIMIT)
    if stems > max_stems:
        raise ValidationError(f"В букете не больше {max_stems} цветков", code="too_many_stems",
                              details={"max_stems": max_stems})
    # упаковка необязательна: букет «без упаковки» — стебли перевязаны лентой

    materials = material_lines(comp)
    items = {
        i.id: i
        for i in InventoryItem.objects.filter(id__in=materials.keys()).select_related("product")
    }
    expected = {}
    roles = [(r["item_id"], C.FLOWER) for r in comp["flowers"]] + [(r["item_id"], C.GREENERY) for r in comp["greenery"]]
    roles += [(comp[k], cat) for k, cat in (("packaging_id", C.PACKAGING), ("ribbon_id", C.RIBBON), ("card_id", C.CARD))
              if comp[k]]
    for item_id, cat in roles:
        if expected.setdefault(item_id, cat) != cat:
            raise ValidationError("В составе есть недоступная позиция", code="invalid_component",
                                  details={"item_id": item_id})

    lines = []
    for item_id, qty in materials.items():
        item = items.get(item_id)
        product = getattr(item, "product", None) if item else None
        if (
            not item or not item.is_active or item.category != expected[item_id] or item.sale_price is None
            or not product or not product.is_active or not product.constructor_enabled
        ):
            raise ValidationError("В составе есть недоступная позиция", code="invalid_component",
                                  details={"item_id": item_id})
        lines.append({
            "item_id": item.id, "name": item.name, "category": item.category, "quantity": qty,
            "unit_price": item.sale_price, "total": item.sale_price * qty,
        })

    if check_stock:
        avail = availability_map(materials.keys())
        for item_id, qty in materials.items():
            need = qty * quantity + (extra_demand or {}).get(item_id, 0)
            if need > avail.get(item_id, 0):
                raise ValidationError(
                    f"«{items[item_id].name}»: доступно только {max(avail.get(item_id, 0) - (extra_demand or {}).get(item_id, 0), 0)}",
                    code="insufficient_stock", details={"item_id": item_id, "available": avail.get(item_id, 0)},
                )

    order_key = {C.FLOWER: 0, C.GREENERY: 1, C.PACKAGING: 2, C.RIBBON: 3, C.CARD: 4}
    lines.sort(key=lambda l: (order_key.get(l["category"], 9), l["name"]))
    materials_total = sum(l["total"] for l in lines)
    unit_price = materials_total + settings.florist_fee
    return {
        "composition": comp,
        "lines": lines,
        "stems": stems,
        "materials_total": materials_total,
        "florist_fee": settings.florist_fee,
        "unit_price": unit_price,
        "quantity": quantity,
        "total": unit_price * quantity,
    }


def design_catalog(comp):
    """Сведения о позициях эскиза (название, вид, цвет), чтобы нарисовать букет без отдельного запроса.
    Работает и для позиций, которые уже сняты с продажи."""
    from apps.catalog.models import Product

    ids = {row.get("item_id") for row in (comp.get("flowers") or []) + (comp.get("greenery") or [])}
    ids |= {comp.get(k) for k in ("packaging_id", "ribbon_id", "card_id")}
    ids = {i for i in ids if isinstance(i, int)}
    if not ids:
        return []
    rows = Product.objects.filter(inventory_item_id__in=ids).only(
        "inventory_item_id", "name", "species", "color_hex", "type", "constructor_image").prefetch_related("images")
    out = []
    for r in rows:
        photo = next(iter(r.images.all()), None)
        out.append({"id": r.inventory_item_id, "name": r.name, "species": r.species, "color_hex": r.color_hex,
                    "type": r.type, "constructor_image": r.constructor_image.url if r.constructor_image else None,
                    "image": photo.image.url if photo and photo.image else None})
    missing = ids - {r["id"] for r in out}
    if missing:  # товар удалён владельцем, но складская позиция осталась в архиве — рисуем по названию
        from apps.inventory.models import InventoryItem

        for it in InventoryItem.objects.filter(pk__in=missing).only("id", "name", "category"):
            out.append({"id": it.pk, "name": it.name, "species": "", "color_hex": "", "type": it.category,
                        "constructor_image": None, "image": None})
    return out

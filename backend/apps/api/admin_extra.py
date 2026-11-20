"""Админка: категории витрины, страница «О нас» и «Частые вопросы»."""
from django.db import transaction
from django.db.models import Max
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.catalog import categories as cats
from apps.catalog.models import Category, Product
from apps.core import site_content
from apps.core import validation as v
from apps.core.audit import audit
from apps.core.errors import NotFound
from apps.core.models import AboutPhoto, ShopSettings

from . import serializers as ser
from .admin_views import _check_image, _int, doc
from .permissions import FloristOrOwner, OwnerOnly


# ------------------------------------------------------------------ категории

def _category(c, counts):
    return {"id": c.id, "kind": c.kind, "kind_label": c.get_kind_display(), "name": c.name,
            "sort_order": c.sort_order, "products": counts.get((c.kind, c.name), 0)}


def _categories(kind=None):
    counts = {}
    for p in Product.objects.filter(type__in=["bouquet", "flower", "greenery"]).values("type", "category"):
        k = cats.kind_of(p["type"])
        counts[(k, p["category"])] = counts.get((k, p["category"]), 0) + 1
    qs = Category.objects.all()
    if kind:
        qs = qs.filter(kind=kind)
    rows = [_category(c, counts) for c in qs]
    return rows, counts


def _list_response(kind):
    rows, counts = _categories(kind)
    without = counts.get((kind, ""), 0) if kind else 0
    return {"categories": rows, "without_category": without}


@doc("Категории витрины ?kind=bouquet|flower; POST {kind, name}")
@api_view(["GET", "POST"])
@permission_classes([FloristOrOwner])
def category_list(request):
    if request.method == "POST":
        c = cats.create(request.data.get("kind"), request.data.get("name"))
        audit(request.user, "category_create", c, request=request, name=c.name)
        return Response(_list_response(c.kind), status=201)
    kind = request.query_params.get("kind") or None
    if kind:
        v.choice(kind, "kind", "Раздел", Category.Kind.values)
    return Response(_list_response(kind))


@doc("Переименовать {name} или удалить категорию ?move_to=<id> (товары переносятся или остаются без категории)")
@api_view(["PATCH", "DELETE"])
@permission_classes([FloristOrOwner])
def category_detail(request, category_id):
    c = cats.get(category_id)
    kind = c.kind
    if request.method == "DELETE":
        name = c.name
        move_to = request.query_params.get("move_to") or request.data.get("move_to")
        moved = cats.delete(c, move_to)
        audit(request.user, "category_delete", request=request, name=name, moved=moved, move_to=move_to)
        return Response({**_list_response(kind), "moved": moved})
    old = c.name
    cats.rename(c, request.data.get("name"))
    audit(request.user, "category_rename", c, request=request, old=old, name=c.name)
    return Response(_list_response(kind))


@doc("Добавить товары в категорию {product_ids:[...]}")
@api_view(["POST"])
@permission_classes([FloristOrOwner])
def category_products(request, category_id):
    c = cats.get(category_id)
    n = cats.add_products(c, request.data.get("product_ids"))
    audit(request.user, "category_add_products", c, request=request, count=n)
    return Response({**_list_response(c.kind), "updated": n})


@doc("Порядок категорий {kind, ids:[...]} — сверху вниз, как на витрине")
@api_view(["POST"])
@permission_classes([FloristOrOwner])
def category_order(request):
    kind = request.data.get("kind")
    cats.reorder(kind, request.data.get("ids"))
    audit(request.user, "category_reorder", request=request, kind=kind)
    return Response(_list_response(kind))


# ------------------------------------------------------------------ «О нас» (владелец)

def about_data(s=None):
    s = s or ShopSettings.load()
    return {"title": s.about_title, "lead": s.about_lead, "text": s.about_text,
            "photos": [{"id": p.id, "url": ser.media_url(p.image), "caption": p.caption, "sort_order": p.sort_order}
                       for p in AboutPhoto.objects.all()]}


@doc("Страница «О нас»: заголовок, вступление, текст {title, lead, text}")
@api_view(["GET", "PATCH"])
@permission_classes([OwnerOnly])
def about(request):
    s = ShopSettings.load()
    if request.method == "PATCH":
        d = request.data
        if "title" in d:
            s.about_title = v.text(d["title"], "title", "Заголовок", required=True, min_len=2, max_len=120)
        if "lead" in d:
            s.about_lead = v.text(d["lead"], "lead", "Вступление", max_len=300)
        if "text" in d:
            s.about_text = v.text(d["text"], "text", "Текст", max_len=10000, multiline=True)
        s.save(update_fields=["about_title", "about_lead", "about_text", "updated_at"])
        audit(request.user, "about_update", s, request=request)
    return Response(about_data(s))


MAX_ABOUT_PHOTOS = 12


@doc("Добавить фото в карусель «О нас» (multipart: image, caption)")
@api_view(["POST"])
@permission_classes([OwnerOnly])
def about_photo_upload(request):
    if AboutPhoto.objects.count() >= MAX_ABOUT_PHOTOS:
        v.fail("image", f"В карусели уже {MAX_ABOUT_PHOTOS} фото — удалите лишние")
    f = _check_image(request.FILES.get("image"))
    caption = v.text(request.data.get("caption"), "caption", "Подпись", max_len=140)
    top = AboutPhoto.objects.aggregate(m=Max("sort_order"))["m"] or 0
    ph = AboutPhoto.objects.create(image=f, caption=caption, sort_order=top + 10)
    audit(request.user, "about_photo_upload", ph, request=request)
    return Response(about_data(), status=201)


@doc("Изменить подпись {caption} или удалить фото карусели")
@api_view(["PATCH", "DELETE"])
@permission_classes([OwnerOnly])
def about_photo_detail(request, photo_id):
    ph = AboutPhoto.objects.filter(pk=_int(photo_id)).first()
    if not ph:
        raise NotFound("Фото не найдено")
    if request.method == "DELETE":
        audit(request.user, "about_photo_delete", ph, request=request)
        ph.image.delete(save=False)
        ph.delete()
    else:
        ph.caption = v.text(request.data.get("caption"), "caption", "Подпись", max_len=140)
        ph.save(update_fields=["caption"])
    return Response(about_data())


@doc("Порядок фото карусели {ids:[...]}")
@api_view(["POST"])
@permission_classes([OwnerOnly])
def about_photo_order(request):
    photos = {p.pk: p for p in AboutPhoto.objects.all()}
    try:
        ids = [int(i) for i in request.data.get("ids") or []]
    except (TypeError, ValueError):
        v.fail("ids", "Некорректный порядок")
    if set(ids) != set(photos):
        v.fail("ids", "Передайте все фото карусели")
    with transaction.atomic():
        for n, pk in enumerate(ids):
            AboutPhoto.objects.filter(pk=pk).update(sort_order=(n + 1) * 10)
    return Response(about_data())


# ------------------------------------------------------------------ «Частые вопросы» (владелец)

def faq_data(s=None):
    s = s or ShopSettings.load()
    return {"blocks": site_content.faq_blocks(s), "custom": s.faq is not None}


@doc("Частые вопросы на главной: GET; PUT {blocks:[{title, items:[{q, a}]}]} — сохранить; "
     "DELETE — вернуть стандартные вопросы (собираются из настроек)")
@api_view(["GET", "PUT", "DELETE"])
@permission_classes([OwnerOnly])
def faq(request):
    s = ShopSettings.load()
    if request.method == "PUT":
        s.faq = site_content.clean_faq(request.data.get("blocks"))
        s.save(update_fields=["faq", "updated_at"])
        audit(request.user, "faq_update", s, request=request, blocks=len(s.faq),
              questions=sum(len(b["items"]) for b in s.faq))
    elif request.method == "DELETE":
        s.faq = None
        s.save(update_fields=["faq", "updated_at"])
        audit(request.user, "faq_reset", s, request=request)
    return Response(faq_data(s))


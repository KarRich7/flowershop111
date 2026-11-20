"""Фото для конструктора: «настоящие» цветы вместо рисунков."""
from io import BytesIO

import numpy as np
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageDraw

from apps.catalog import builder, cutout
from apps.catalog.models import Product

from .conftest import staff_client


def _photo(fmt="JPEG", bg=(239, 230, 216), size=(300, 360)):
    """Красный «бутон» на однотонном кремовом фоне — как фото со стола флориста."""
    im = Image.new("RGB", size, bg)
    ImageDraw.Draw(im).ellipse((90, 80, 210, 200), fill=(170, 20, 40))
    buf = BytesIO()
    im.save(buf, fmt)
    buf.seek(0)
    return buf


def test_plain_background_is_removed_and_trimmed():
    prepared = cutout.prepare(_photo(), "flower")
    assert prepared.background_removed
    im = Image.open(BytesIO(prepared.file.read()))
    assert im.format == "WEBP" and im.mode == "RGBA"
    a = np.asarray(im)[..., 3]
    assert im.size[0] <= 150 and im.size[1] <= 150  # обрезано по бутону (кадр был 300×360)
    assert a[0, 0] < 20 and a[im.size[1] // 2, im.size[0] // 2] > 240  # угол прозрачный, центр — нет


def test_busy_background_is_kept_with_note():
    rng = np.random.default_rng(1)
    noisy = Image.fromarray(rng.integers(0, 255, (200, 200, 3), dtype=np.uint8))
    buf = BytesIO()
    noisy.save(buf, "PNG")
    buf.seek(0)
    prepared = cutout.prepare(buf, "flower")
    assert not prepared.background_removed and prepared.note


def test_packaging_becomes_square_texture():
    prepared = cutout.prepare(_photo(size=(600, 400)), "packaging")
    im = Image.open(BytesIO(prepared.file.read()))
    assert im.size == (cutout.TEXTURE_SIDE, cutout.TEXTURE_SIDE)


@pytest.mark.django_db
def test_florist_uploads_constructor_photo_and_it_reaches_constructor(shop, staff, web, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    rose = Product.objects.get(inventory_item=shop.rose)
    florist = staff_client("florist")
    f = SimpleUploadedFile("rose.jpg", _photo().read(), content_type="image/jpeg")
    r = florist.post(f"/api/v1/admin/products/{rose.id}/constructor-image", {"image": f}, format="multipart")
    assert r.status_code == 200, r.content
    url = r.json()["constructor_image"]
    assert url.startswith("/media/constructor/") and url.endswith(".webp")
    assert "Фон убран" in r.json()["constructor_image_note"]
    # публичный конструктор и эскиз заказа получают фото
    opts = web.get("/api/v1/constructor/options").json()
    assert next(x for x in opts["flowers"] if x["id"] == rose.id)["constructor_image"] == url
    items = builder.design_catalog(shop.custom_composition())
    assert next(i for i in items if i["id"] == shop.rose.id)["constructor_image"] == url
    # курьер не может менять фото, флорист может удалить
    assert staff_client("courier1").delete(f"/api/v1/admin/products/{rose.id}/constructor-image").status_code == 403
    r = florist.delete(f"/api/v1/admin/products/{rose.id}/constructor-image")
    assert r.status_code == 200 and r.json()["constructor_image"] is None


@pytest.mark.django_db
def test_demo_constructor_photos_attach_to_existing_demo_db(shop, settings, tmp_path):
    from apps.catalog.models import ProductImage
    from apps.core.management.commands.seed_demo import attach_constructor_images

    settings.MEDIA_ROOT = tmp_path
    rose = Product.objects.get(inventory_item=shop.rose)
    Product.objects.filter(pk=rose.pk).update(is_demo=True)
    ProductImage.objects.create(product=rose, image="products/f01.jpg")
    assert attach_constructor_images() == 1
    rose.refresh_from_db()
    assert rose.constructor_image.name == "constructor/f01.webp"
    assert (tmp_path / "constructor" / "f01.webp").is_file()
    assert attach_constructor_images() == 0  # повторный запуск ничего не меняет

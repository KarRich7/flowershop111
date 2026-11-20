"""Подготовка фото для конструктора букетов.

Цветы и зелень: нужен бутон (ветка) без фона. Если загружен PNG/WebP с прозрачностью — берём как есть.
Иначе фон убирается автоматически:
  1) нейросетью IS-Net (apps.catalog.segment) — подходит любой фон: стол, ваза, витрина;
  2) если модели нет — простым алгоритмом для однотонного фона (цвет фона по краям кадра).
Весь вырезанный объект сохраняется как «исходная вырезка» (constructor_source), а в конструктор
идёт кадр с одним бутоном: для цветов он находится автоматически (самое крупное цветное пятно
в верхней части фото), флорист может поправить рамку в админке. Результат — WebP до 480 px.

Упаковка: фрагмент материала (текстура) — центральный квадрат 256×256.
"""
from dataclasses import dataclass, field
from io import BytesIO

import numpy as np
from django.core.files.base import ContentFile
from PIL import Image, ImageFilter, ImageOps

CUTOUT_TYPES = {"flower", "greenery"}
MAX_SIDE = 480
SOURCE_SIDE = 1200
TEXTURE_SIDE = 256


@dataclass
class Prepared:
    file: ContentFile
    background_removed: bool
    note: str = ""
    source: ContentFile | None = None
    crop: dict = field(default_factory=dict)


def _has_transparency(img: Image.Image) -> bool:
    if img.mode not in ("RGBA", "LA", "PA") and "transparency" not in img.info:
        return False
    a = np.asarray(img.convert("RGBA"))[..., 3]
    return bool((a < 250).mean() > 0.02)


def remove_plain_background(img: Image.Image):
    """Убирает однотонный фон. Возвращает (RGBA, ok). ok=False — фон неоднородный, картинка не изменена."""
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
    h, w = rgb.shape[:2]
    b = max(2, min(h, w) // 40)
    border = np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3),
                             rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    spread = float(np.percentile(np.linalg.norm(border - bg, axis=1), 90))
    if spread > 38:
        return img.convert("RGBA"), False
    dist = np.linalg.norm(rgb - bg, axis=2)
    t0 = spread + 10
    alpha = np.clip((dist - t0) / 26.0, 0, 1)
    a_img = Image.fromarray((alpha * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
    alpha = np.asarray(a_img, dtype=np.float32) / 255
    a3 = np.clip(alpha, 1e-3, 1)[..., None]
    fg = np.where(a3 > 0.12, (rgb - (1 - a3) * bg) / a3, rgb)  # чистим кромку от цвета фона
    out = np.dstack([np.clip(fg, 0, 255), alpha * 255]).astype(np.uint8)
    return Image.fromarray(out, "RGBA"), True


def _trim(img: Image.Image) -> Image.Image:
    box = img.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
    return img.crop(box) if box else img


def _webp(img, name, quality=90):
    buf = BytesIO()
    img.save(buf, "WEBP", quality=quality, method=4)
    return ContentFile(buf.getvalue(), name=name)


def _erode(m):
    out = m.copy()
    out[1:-1, 1:-1] = m[1:-1, 1:-1] & m[:-2, 1:-1] & m[2:, 1:-1] & m[1:-1, :-2] & m[1:-1, 2:]
    out[0, :] = out[-1, :] = False
    out[:, 0] = out[:, -1] = False
    return out


def find_head(rgba: Image.Image) -> dict:
    """Кадр с одним бутоном (доли 0..1 от вырезки).

    Маска «лепестков» — плотные нелиственные пиксели (стекло вазы и блики полупрозрачны и
    отсекаются). Для каждой точки считаем, сколько сжатий маски она переживает (≈ расстояние
    до края); максимум — центр самого крупного бутона, даже если бутоны соприкасаются.
    Верхние бутоны в приоритете: ваза и стебли внизу кадра."""
    full = {"x": 0, "y": 0, "w": 1, "h": 1}
    W, H = rgba.size
    k = 160 / max(W, H)
    small = rgba.resize((max(1, round(W * k)), max(1, round(H * k))), Image.BILINEAR)
    a = np.asarray(small.getchannel("A"), dtype=np.float32) / 255
    hsv = np.asarray(small.convert("RGB").convert("HSV"), dtype=np.float32) / 255
    hue, sat, val = hsv[..., 0] * 360, hsv[..., 1], hsv[..., 2]
    leafy = (hue > 55) & (hue < 170) & (sat > 0.18)
    petals = (a > 0.88) & ~leafy & (val > 0.25) & ((sat > 0.22) | (val > 0.72))
    if petals.sum() < 20:
        return full
    h, w = petals.shape
    dist = np.zeros((h, w), dtype=np.float32)
    m = petals.copy()
    while m.any():
        dist += m
        m = _erode(m)
    ys = (np.arange(h, dtype=np.float32) / h)[:, None]
    weight = (1.3 - 0.6 * ys) * np.where(ys > 0.72, 0.3, 1.0)
    cy, cx = np.unravel_index(np.argmax(dist * weight), dist.shape)
    r = float(dist[cy, cx])
    if r < 2:
        return full
    side = max(r * 2 * 1.7 / k, 0.22 * max(W, H))  # головка шире вписанного круга: запас на края лепестков
    side = min(side, W, H)
    bw, bh = side / W, side / H
    if bw > 0.92 and bh > 0.92:
        return full
    x = min(max((cx + 0.5) / w - bw / 2, 0), 1 - bw)
    y = min(max((cy + 0.5) / h - bh / 2, 0), 1 - bh)
    return {"x": round(float(x), 4), "y": round(float(y), 4), "w": round(float(bw), 4), "h": round(float(bh), 4)}


def clean_crop(box) -> dict:
    """Проверяет рамку {x, y, w, h} (доли 0..1)."""
    from apps.core.errors import ValidationError

    try:
        x, y, w, h = (float(box[k]) for k in ("x", "y", "w", "h"))
    except (TypeError, ValueError, KeyError):
        raise ValidationError("Некорректная рамка", details={"field": "crop"})
    if not (0.05 <= w <= 1.0 and 0.05 <= h <= 1.0):
        raise ValidationError("Рамка слишком маленькая", details={"field": "crop"})
    x, y = min(max(x, 0.0), 1.0 - w), min(max(y, 0.0), 1.0 - h)
    return {"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)}


def crop_image(source: Image.Image, box: dict) -> ContentFile:
    W, H = source.size
    part = source.crop((round(box["x"] * W), round(box["y"] * H),
                        round((box["x"] + box["w"]) * W), round((box["y"] + box["h"]) * H)))
    part = _trim(part.convert("RGBA"))
    part.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    return _webp(part, "cutout.webp")


def prepare(fileobj, product_type: str, remove_background: bool = True, crop="auto") -> Prepared:
    from . import segment

    img = ImageOps.exif_transpose(Image.open(fileobj))
    img.load()
    if product_type in CUTOUT_TYPES:
        img.thumbnail((1600, 1600), Image.LANCZOS)
        removed, note = False, ""
        if _has_transparency(img):
            rgba = img.convert("RGBA")
        elif remove_background:
            rgba = None
            if segment.available():
                try:
                    rgba = segment.cut(img)
                except Exception:  # noqa: BLE001 — сбой модели не должен ломать загрузку
                    rgba = None
                removed = rgba is not None
            if rgba is None:
                rgba, removed = remove_plain_background(img)
            if not removed:
                note = "Фон убрать не получилось — загрузите фото на однотонном фоне или PNG без фона."
        else:
            rgba = img.convert("RGBA")
        source = _trim(rgba)
        source.thumbnail((SOURCE_SIDE, SOURCE_SIDE), Image.LANCZOS)
        if isinstance(crop, dict):
            box = clean_crop(crop)
        elif crop == "auto" and product_type == "flower":
            box = find_head(source)
        else:
            box = {"x": 0, "y": 0, "w": 1, "h": 1}
        if box != {"x": 0, "y": 0, "w": 1, "h": 1}:
            note = (note + " " if note else "") + "Бутон выделен автоматически — при необходимости поправьте рамку."
        return Prepared(crop_image(source, box), removed, note.strip(), _webp(source, "source.webp", 92), box)
    # текстура материала: центральный квадрат
    rgb = img.convert("RGB")
    side = min(rgb.size)
    left, top = (rgb.width - side) // 2, (rgb.height - side) // 2
    rgb = rgb.crop((left, top, left + side, top + side)).resize((TEXTURE_SIDE, TEXTURE_SIDE), Image.LANCZOS)
    buf = BytesIO()
    rgb.save(buf, "JPEG", quality=88)
    return Prepared(ContentFile(buf.getvalue(), name="texture.jpg"), False)

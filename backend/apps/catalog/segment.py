"""Автоматическое отделение цветка от фона нейросетью IS-Net (DIS, isnet-general-use, Apache-2.0).

Модель (~170 МБ, ONNX) скачивается при сборке Docker-образа; путь — CUTOUT_MODEL_PATH.
Если onnxruntime или файла модели нет, available() == False и используется простой
алгоритм для однотонного фона (cutout.remove_plain_background).
"""
import logging
import os
import threading

import numpy as np
from django.conf import settings
from PIL import Image

logger = logging.getLogger(__name__)
SIZE = 1024
_lock = threading.Lock()
_session = None
_failed = False


def model_path():
    return getattr(settings, "CUTOUT_MODEL_PATH", "") or ""


def available():
    if _failed:
        return False
    p = model_path()
    if not p or not os.path.exists(p):
        return False
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def _get_session():
    global _session, _failed
    if _session is None:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, min(4, os.cpu_count() or 1))
        try:
            _session = ort.InferenceSession(model_path(), sess_options=opts, providers=["CPUExecutionProvider"])
        except Exception:  # noqa: BLE001
            _failed = True
            logger.exception("Не удалось загрузить модель вырезки фона %s", model_path())
            raise
    return _session


def mask(img: Image.Image) -> np.ndarray:
    """Маска объекта 0..1 размером с исходное изображение."""
    rgb = img.convert("RGB")
    x = np.asarray(rgb.resize((SIZE, SIZE), Image.LANCZOS), dtype=np.float32)
    x = x / max(float(x.max()), 1.0)
    x = (x - np.array([0.485, 0.456, 0.406], dtype=np.float32)) / 1.0
    x = np.expand_dims(x.transpose(2, 0, 1), 0).astype(np.float32)
    with _lock:  # одна модель на процесс: запросы флористов идут по очереди, без лишней памяти
        sess = _get_session()
        out = sess.run(None, {sess.get_inputs()[0].name: x})[0][0, 0]
    lo, hi = float(out.min()), float(out.max())
    m = (out - lo) / (hi - lo + 1e-6)
    m_img = Image.fromarray((m * 255).astype(np.uint8), "L").resize(rgb.size, Image.LANCZOS)
    return np.asarray(m_img, dtype=np.float32) / 255.0


def cut(img: Image.Image):
    """RGBA с прозрачным фоном или None, если объект не найден."""
    m = mask(img)
    if (m > 0.5).mean() < 0.005:
        return None
    alpha = np.clip((m - 0.08) / 0.84, 0, 1)  # чуть плотнее середина, мягкая кромка
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
    bg_px = rgb[alpha < 0.03]
    if len(bg_px) > 100:  # убираем ореол цвета фона на полупрозрачной кромке
        bg = np.median(bg_px, axis=0)
        a3 = np.clip(alpha, 1e-3, 1)[..., None]
        rgb = np.where((a3 > 0.15) & (a3 < 0.98), np.clip((rgb - (1 - a3) * bg) / a3, 0, 255), rgb)
    return Image.fromarray(np.dstack([rgb, alpha * 255]).astype(np.uint8), "RGBA")

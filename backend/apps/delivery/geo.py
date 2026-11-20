"""Геокодирование адресов и определение зоны доставки по координатам.

* Провайдер — Яндекс HTTP Геокодер (если задан ключ) или Nominatim / OpenStreetMap (без ключа).
* Зона определяется на сервере: точка должна попасть в один из многоугольников активной зоны.
* Адрес, найденный геокодером, подписывается HMAC-токеном: при оформлении заказа сервер проверяет,
  что адрес и координаты не подменены, и не обращается к геокодеру повторно.
"""
import hashlib
import hmac
import json
import logging
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Магазин — Кондратово (ЖК «Медовый»), Пермский край. Доставка: Кондратово, Пермь и ближайшие сёла.
SHOP_POINT = (57.98644, 56.11818)
CITY_CENTER = (58.0000, 56.2000)  # центр области поиска (между Кондратово и Пермью)
# Область поиска: Кондратово, Пермь и пригород (широта/долгота)
SEARCH_BOX = {"lat_min": 57.80, "lat_max": 58.25, "lon_min": 55.70, "lon_max": 56.70}
REGION = "Пермский край"
CACHE_TTL = 60 * 60 * 24


class GeocoderUnavailable(Exception):
    """Геокодер не настроен или не отвечает — проверку адреса нужно пропустить или отложить."""

    def __init__(self, message, detail=""):
        super().__init__(message)
        self.message, self.detail = message, detail or message

    def __str__(self):
        return self.message


@dataclass
class GeoResult:
    address: str  # короткий адрес для курьера: «Кондратово, Красавинская улица, 8»
    full_address: str
    lat: float
    lon: float
    house: bool  # найден конкретный дом
    precision: str = ""

    def to_dict(self):
        return asdict(self)


# ------------------------------------------------------------------ геометрия

def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def point_in_ring(lat, lon, ring):
    """Ray casting. ring — список точек [широта, долгота]."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        yi, xi = ring[i][0], ring[i][1]
        yj, xj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def zone_contains(zone, lat, lon):
    return any(point_in_ring(lat, lon, ring) for ring in (zone.polygons or []) if len(ring) >= 3)


def find_zone(lat, lon, zones=None):
    """Активная зона, в которую попадает точка. При пересечении границ — зона с меньшим порядком сортировки."""
    from .models import DeliveryZone

    zones = zones if zones is not None else DeliveryZone.objects.filter(is_active=True).order_by("sort_order", "id")
    for z in zones:
        if zone_contains(z, lat, lon):
            return z
    return None


def validate_polygons(value):
    """Проверка границ зоны из админки: [[ [lat, lon], ... ], ...]."""
    from apps.core.errors import ValidationError

    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise ValidationError("Границы зоны: некорректный формат")
    if not isinstance(value, list):
        raise ValidationError("Границы зоны: ожидается список многоугольников")
    out = []
    for ring in value:
        if not isinstance(ring, list) or len(ring) < 3:
            raise ValidationError("В каждом многоугольнике должно быть не меньше трёх точек")
        pts = []
        for pt in ring:
            try:
                lat, lon = float(pt[0]), float(pt[1])
            except (TypeError, ValueError, IndexError):
                raise ValidationError("Границы зоны: точка должна быть парой [широта, долгота]")
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValidationError("Границы зоны: координаты вне допустимого диапазона")
            pts.append([round(lat, 6), round(lon, 6)])
        if len(pts) > 2000:
            raise ValidationError("Слишком подробный контур зоны (больше 2000 точек)")
        out.append(pts)
    if len(out) > 20:
        raise ValidationError("Не больше 20 многоугольников в одной зоне")
    return out


# ------------------------------------------------------------------ подпись проверенного адреса

def _sig_payload(address, lat, lon):
    return f"{(address or '').strip()}|{float(lat):.6f}|{float(lon):.6f}"


def sign(address, lat, lon):
    msg = _sig_payload(address, lat, lon).encode()
    return hmac.new(f"geo:{settings.SECRET_KEY}".encode(), msg, hashlib.sha256).hexdigest()[:32]


def verify(address, lat, lon, token):
    if not token:
        return False
    try:
        return hmac.compare_digest(sign(address, lat, lon), str(token))
    except (TypeError, ValueError):
        return False


# ------------------------------------------------------------------ провайдеры

YANDEX_DOWN_KEY = "geo:yandex:down"
YANDEX_DOWN_SECONDS = 10 * 60


def _yandex_count_key():
    from apps.core.utils import local_today

    return f"geo:yandex:count:{local_today().isoformat()}"


def yandex_used_today():
    return int(cache.get(_yandex_count_key()) or 0)


def _yandex_count():
    """Счётчик запросов к Яндексу за сутки: бесплатный тариф — 1000 запросов в день, дальше Яндекс
    блокирует ключ. После YANDEX_GEOCODER_DAILY_LIMIT запросов до полуночи работаем через Nominatim."""
    key = _yandex_count_key()
    if cache.add(key, 1, 2 * 24 * 3600):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, 2 * 24 * 3600)
        return 1


def _yandex_limit_reached():
    limit = int(getattr(settings, "YANDEX_GEOCODER_DAILY_LIMIT", 0) or 0)
    return limit > 0 and yandex_used_today() >= limit


def provider():
    p = (settings.GEOCODER_PROVIDER or "auto").lower()
    if p == "auto":
        if not settings.YANDEX_GEOCODER_API_KEY or cache.get(YANDEX_DOWN_KEY) or _yandex_limit_reached():
            return "nominatim"  # нет ключа, Яндекс недавно отказал или исчерпан дневной лимит
        return "yandex"
    return p


def _yandex_failed(e):
    """В режиме auto при отказе Яндекса на 10 минут переключаемся на Nominatim (OpenStreetMap)."""
    if (settings.GEOCODER_PROVIDER or "auto").lower() != "auto":
        return False
    detail = getattr(e, "detail", str(e))
    cache.set(YANDEX_DOWN_KEY, detail[:200], YANDEX_DOWN_SECONDS)
    logger.warning("Яндекс Геокодер недоступен (%s) — на %s мин переключаемся на Nominatim. "
                   "Проверьте ключ: python manage.py check_maps", detail, YANDEX_DOWN_SECONDS // 60)
    return True


def enabled():
    return provider() in ("yandex", "nominatim")


def _http_json(url, params, headers=None):
    full = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(full, headers={"User-Agent": settings.GEOCODER_USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=settings.GEOCODER_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001 — сеть, таймаут, 4xx/5xx
        detail = str(e)
        if isinstance(e, urllib.error.HTTPError):
            try:
                detail = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
            except Exception:  # noqa: BLE001
                detail = f"HTTP {e.code}"
        logger.warning("geocoder request failed: %s", detail)
        raise GeocoderUnavailable("Сервис проверки адресов временно недоступен", detail) from e


def _in_box(lat, lon):
    b = SEARCH_BOX
    return b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]


def _short(street, house, locality):
    """Населённый пункт пишем всегда: курьер ездит и по Кондратово, и по Перми."""
    base = ", ".join(x for x in (street, house) if x)
    if locality:
        base = f"{locality}, {base}" if base else locality
    return base


# --- Nominatim (OpenStreetMap). Политика сервиса: не больше 1 запроса в секунду, без автодополнения.

def _nominatim_throttle():
    for _ in range(20):
        if cache.add("geo:nominatim:lock", 1, 1):
            return
        time.sleep(0.1)


def _nominatim_parse(r):
    a = r.get("address") or {}
    street = a.get("road") or a.get("pedestrian") or a.get("square") or a.get("neighbourhood") or ""
    house = a.get("house_number") or ""
    locality = a.get("city") or a.get("town") or a.get("village") or a.get("hamlet") or ""
    full = r.get("display_name") or ""
    return GeoResult(address=_short(street, house, locality) or full, full_address=full, lat=float(r["lat"]),
                     lon=float(r["lon"]), house=bool(house), precision="house" if house else (r.get("addresstype") or ""))


def _nominatim_search(query, limit):
    _nominatim_throttle()
    b = SEARCH_BOX
    data = _http_json(f"{settings.NOMINATIM_URL}/search", {
        "q": query, "format": "jsonv2", "addressdetails": 1, "limit": limit, "countrycodes": "ru",
        "accept-language": "ru", "bounded": 1, "viewbox": f"{b['lon_min']},{b['lat_max']},{b['lon_max']},{b['lat_min']}",
    })
    return [_nominatim_parse(r) for r in data]


def _nominatim_reverse(lat, lon):
    _nominatim_throttle()
    data = _http_json(f"{settings.NOMINATIM_URL}/reverse", {
        "lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "format": "jsonv2", "zoom": 18, "addressdetails": 1,
        "accept-language": "ru",
    })
    if not data or data.get("error"):
        return None
    res = _nominatim_parse(data)
    # координаты оставляем там, где поставлена метка, — Nominatim возвращает центр здания
    if haversine_m(lat, lon, res.lat, res.lon) > 120:
        res.house = False
    return res


# --- Яндекс HTTP Геокодер

def _yandex_parse(member):
    g = member["GeoObject"]
    meta = g["metaDataProperty"]["GeocoderMetaData"]
    lon, lat = (float(x) for x in g["Point"]["pos"].split())
    comps = {c["kind"]: c["name"] for c in meta.get("Address", {}).get("Components", [])}
    street, house = comps.get("street", ""), comps.get("house", "")
    locality = comps.get("locality", "")
    full = meta.get("Address", {}).get("formatted") or meta.get("text") or g.get("name", "")
    is_house = meta.get("kind") == "house" and meta.get("precision") in ("exact", "number", "near")
    return GeoResult(address=_short(street, house, locality) or g.get("name", full), full_address=full, lat=lat,
                     lon=lon, house=is_house, precision=meta.get("precision", ""))


def _yandex_request(geocode, limit, extra=None):
    b = SEARCH_BOX
    _yandex_count()
    data = _http_json("https://geocode-maps.yandex.ru/1.x/", {
        "apikey": settings.YANDEX_GEOCODER_API_KEY, "geocode": geocode, "format": "json", "lang": "ru_RU",
        "results": limit, "ll": f"{CITY_CENTER[1]},{CITY_CENTER[0]}",
        "spn": f"{b['lon_max'] - b['lon_min']:.2f},{b['lat_max'] - b['lat_min']:.2f}", **(extra or {}),
    }, headers={"Referer": settings.FRONTEND_URL.rstrip("/") + "/"})  # ключ с ограничением по HTTP Referer пропустит запрос
    members = data.get("response", {}).get("GeoObjectCollection", {}).get("featureMember", [])
    return [_yandex_parse(m) for m in members]


def _yandex_search(query, limit):
    return _yandex_request(query, limit, {"rspn": 1})


def _yandex_reverse(lat, lon):
    rows = _yandex_request(f"{lon:.6f},{lat:.6f}", 1, {"kind": "house"})
    if not rows:
        return None
    res = rows[0]
    if haversine_m(lat, lon, res.lat, res.lon) > 120:
        res.house = False
    return res


# ------------------------------------------------------------------ публичные функции

ABBREVIATIONS = [
    (r"\bпр-кт\.?|\bпр-т\.?|\bпросп\.|\bпр\.(?=\s|$)", "проспект "),
    (r"\bул\.", "улица "), (r"\bпер\.", "переулок "), (r"\bб-р\b|\bбул\.", "бульвар "),
    (r"\bпл\.", "площадь "), (r"\bнаб\.", "набережная "), (r"\bш\.", "шоссе "), (r"\bмкр\.?", "микрорайон "),
    (r"\bг\.", ""), (r"\bд\.(?=\s*\d)", ""), (r"\bдом\b(?=\s*\d)", ""),
]
APARTMENT_RE = re.compile(r"[,\s]*\b(квартира|кв\.?|офис|оф\.?|подъезд|под\.?|этаж|эт\.?)\s*№?\s*[\w-]+", re.I)


def _norm_query(q):
    q = " ".join((q or "").replace("\n", " ").split())[:200]
    q = APARTMENT_RE.sub("", q)
    for pattern, repl in ABBREVIATIONS:
        q = re.sub(pattern, repl, q, flags=re.I)
    return " ".join(q.replace(" ,", ",").split()).strip(" ,")


def split_apartment(text):
    """«ул. Красавинская, 8, кв. 12, подъезд 2, этаж 5» → ("ул. Красавинская, 8", {"apartment": "12", ...})."""
    extra = {}
    for key, rx in (("apartment", r"\b(?:квартира|кв\.?|офис|оф\.?)\s*№?\s*([\w-]+)"),
                    ("entrance", r"\b(?:подъезд|под\.?)\s*№?\s*([\w-]+)"), ("floor", r"\b(?:этаж|эт\.?)\s*([\w-]+)")):
        m = re.search(rx, text or "", re.I)
        if m:
            extra[key] = m.group(1)[:20]
    return APARTMENT_RE.sub("", text or "").strip(" ,"), extra


def geocode(query, limit=5, _provider=None):
    """Поиск адреса в Кондратово, Перми и пригороде. Возвращает список GeoResult (дома — первыми)."""
    q = _norm_query(str(query or "")[:300])[:200]
    if len(q) < 3:
        return []
    p = _provider or provider()
    if p not in ("yandex", "nominatim"):
        raise GeocoderUnavailable("Проверка адресов отключена")
    search_q = f"{REGION}, {q}" if REGION.lower() not in q.lower() else q
    key = "geo:s:" + hashlib.md5(f"{p}|{search_q}|{limit}".encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return [GeoResult(**r) for r in cached]
    search = _yandex_search if p == "yandex" else _nominatim_search
    try:
        rows = search(search_q, limit)
    except GeocoderUnavailable as e:
        if p != "yandex" or not _yandex_failed(e):
            raise
        return geocode(query, limit, _provider="nominatim")  # повтор через Nominatim
    if not rows and re.search(r"\d+\s*/\s*\d+", search_q):  # «24/8» — угловой дом: пробуем первую часть
        rows = search(re.sub(r"(\d+)\s*/\s*\d+", r"\1", search_q), limit)
    if not rows and search_q != q:
        rows = search(q, limit)
    rows = [r for r in rows if _in_box(r.lat, r.lon)]
    rows.sort(key=lambda r: not r.house)
    rows = _dedupe(rows)
    cache.set(key, [r.to_dict() for r in rows], CACHE_TTL)
    return rows


def _dedupe(rows):
    """Один и тот же дом OpenStreetMap иногда отдаёт несколько раз (здание и вход) — оставляем одну строку."""
    out = []
    for r in rows:
        if not any(o.address == r.address and haversine_m(o.lat, o.lon, r.lat, r.lon) < 300 for o in out):
            out.append(r)
    return out


def reverse(lat, lon, _provider=None):
    lat, lon = float(lat), float(lon)
    p = _provider or provider()
    if p not in ("yandex", "nominatim"):
        raise GeocoderUnavailable("Проверка адресов отключена")
    key = f"geo:r:{p}:{lat:.5f}:{lon:.5f}"
    cached = cache.get(key)
    if cached is not None:
        return GeoResult(**cached) if cached else None
    try:
        res = _yandex_reverse(lat, lon) if p == "yandex" else _nominatim_reverse(lat, lon)
    except GeocoderUnavailable as e:
        if p != "yandex" or not _yandex_failed(e):
            raise
        return reverse(lat, lon, _provider="nominatim")  # повтор через Nominatim
    if res:
        res.lat, res.lon = lat, lon  # точка доставки — там, где покупатель поставил метку
    cache.set(key, res.to_dict() if res else {}, CACHE_TTL)
    return res


def zone_info(zone, items_total=None):
    if not zone:
        return None
    data = {"id": zone.id, "name": zone.name, "price": zone.price, "free_from": zone.free_from, "color": zone.color}
    if items_total is not None:
        data["cost"] = zone.cost_for(items_total)
    return data


def describe(res):
    """GeoResult → dict для API: адрес, координаты, зона и подпись проверенного адреса."""
    zone = find_zone(res.lat, res.lon)
    d = res.to_dict()
    d["zone"] = zone_info(zone)
    d["token"] = sign(res.address, res.lat, res.lon) if res.house else None
    return d

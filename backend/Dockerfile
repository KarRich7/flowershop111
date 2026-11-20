# Бэкенд «Цветы Урала»: Django + DRF + Celery + боты (один образ, разные команды)
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MEDIA_ROOT=/app/media

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# Модель IS-Net для автоматического вырезания цветов из фото (~180 МБ).
# Собрать без неё: docker compose build --build-arg CUTOUT_MODEL_URL= backend
# (тогда фон убирается простым алгоритмом — нужен однотонный фон на фото).
ARG CUTOUT_MODEL_URL=https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx
ENV CUTOUT_MODEL_PATH=/opt/models/isnet-general-use.onnx
RUN mkdir -p /opt/models && if [ -n "$CUTOUT_MODEL_URL" ]; then \
      python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" \
        "$CUTOUT_MODEL_URL" "$CUTOUT_MODEL_PATH" || echo "Модель не скачалась — будет простой алгоритм"; \
    fi

COPY . .
RUN DJANGO_DEBUG=true python manage.py collectstatic --noinput \
    && chmod +x docker/entrypoint.sh \
    && useradd --create-home --uid 1000 app && mkdir -p /app/media && chown -R app:app /app
USER app

EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["web"]

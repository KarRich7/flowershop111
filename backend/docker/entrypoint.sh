#!/bin/sh
# Точка входа контейнеров бэкенда.
#   web      — миграции, демо-данные (если БД пустая), gunicorn
#   worker   — Celery worker (уведомления, фоновые задачи)
#   beat     — Celery beat (снятие просроченных резервов каждые 60 с)
#   telegram — Telegram-бот (без TELEGRAM_BOT_TOKEN завершится с кодом 0)
#   vk       — ВК-бот (без VK_GROUP_TOKEN/VK_GROUP_ID завершится с кодом 0)
#   gen-secrets — напечатать новые случайные секреты для .env (ничего не меняет)
#   любая другая команда выполняется как есть (например: python manage.py shell)
set -e

wait_for_db() {
  echo "Ожидание PostgreSQL ${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432}…"
  i=0
  until pg_isready -h "${POSTGRES_HOST:-db}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-flowers}" >/dev/null 2>&1; do
    i=$((i+1)); [ "$i" -gt 60 ] && echo "PostgreSQL недоступен" && exit 1
    sleep 1
  done
}

case "$1" in
  web)
    wait_for_db
    python manage.py migrate --noinput
    if [ "${SEED_DEMO:-true}" = "true" ]; then
      python manage.py seed_demo --if-empty
    fi
    # учётная запись владельца из OWNER_USERNAME / OWNER_PASSWORD, если владельца ещё нет
    python manage.py ensure_owner
    python manage.py security_check --quiet || true
    # gthread: медленные клиенты не занимают процесс целиком; лимиты на размер заголовков — защита от «тяжёлых» запросов;
    # max-requests — процессы периодически перезапускаются (защита от утечек памяти)
    exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 \
      --workers "${GUNICORN_WORKERS:-3}" --worker-class gthread --threads "${GUNICORN_THREADS:-4}" \
      --timeout 30 --graceful-timeout 20 --keep-alive 5 \
      --max-requests 1000 --max-requests-jitter 100 \
      --limit-request-line 4094 --limit-request-fields 100 --limit-request-field_size 8190 \
      --access-logfile - --logger-class config.log_masking.MaskingLogger
    ;;
  gen-secrets)
    exec python - <<'PY'
import secrets
print("# Новые секреты — вставьте в .env вместо старых значений (храните в тайне):")
print("DJANGO_SECRET_KEY=" + secrets.token_urlsafe(50))
print("PAYMENT_SIMULATOR_SECRET=" + secrets.token_urlsafe(32))
print("BOT_SERVICE_TOKEN=" + secrets.token_urlsafe(32))
print("# Пароль базы: если база уже создана, сначала смените его в самой базе (см. docs/SECURITY.md)")
print("POSTGRES_PASSWORD=" + secrets.token_urlsafe(24))
PY
    ;;
  worker)
    wait_for_db
    exec celery -A config worker -l "${CELERY_LOG_LEVEL:-info}" --concurrency "${CELERY_CONCURRENCY:-2}"
    ;;
  beat)
    wait_for_db
    exec celery -A config beat -l "${CELERY_LOG_LEVEL:-info}" --schedule /tmp/celerybeat-schedule
    ;;
  telegram)
    wait_for_db
    exec python manage.py run_telegram_bot
    ;;
  vk)
    wait_for_db
    exec python manage.py run_vk_bot
    ;;
  *)
    exec "$@"
    ;;
esac

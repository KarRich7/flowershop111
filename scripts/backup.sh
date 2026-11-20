#!/bin/sh
# Резервная копия PostgreSQL (сжатый custom-формат pg_dump).
#   ./scripts/backup.sh            — одна копия в ./backups (нужны PG* переменные или .env)
#   ./scripts/backup.sh --loop     — бесконечный цикл (используется контейнером db-backup)
# Кроме базы в контейнере db-backup архивируются фото (том media → backups/media_*.tar.gz,
# BACKUP_MEDIA=false — не архивировать, BACKUP_MEDIA_KEEP — сколько архивов хранить, по умолчанию 3).
# Восстановление:
#   pg_restore --clean --if-exists -h localhost -U flowers -d flowers backups/flowers_YYYYmmdd_HHMMSS.dump
#   или в Docker: docker compose exec -T db pg_restore --clean --if-exists -U flowers -d flowers < backups/<файл>.dump
#   фото: docker compose exec -T backend tar xzf - -C /app < backups/media_YYYYmmdd_HHMMSS.tar.gz
set -e
if [ -n "$BACKUP_DIR" ]; then DIR="$BACKUP_DIR"
elif [ -d /backups ]; then DIR=/backups          # внутри контейнера db-backup
else DIR="$(dirname "$0")/../backups"; fi
mkdir -p "$DIR"
KEEP="${BACKUP_KEEP:-7}"

one_backup() {
  f="$DIR/${PGDATABASE:-flowers}_$(date +%Y%m%d_%H%M%S).dump"
  pg_dump -Fc -f "$f.tmp" && mv "$f.tmp" "$f"
  echo "$(date '+%F %T') backup ok: $f"
  ls -1t "$DIR"/*.dump 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
  if [ "${BACKUP_MEDIA:-true}" != "false" ] && [ -d /media ]; then
    m="$DIR/media_$(date +%Y%m%d_%H%M%S).tar.gz"
    tar czf "$m.tmp" -C / media && mv "$m.tmp" "$m"
    echo "$(date '+%F %T') media backup ok: $m"
    ls -1t "$DIR"/media_*.tar.gz 2>/dev/null | tail -n +$((${BACKUP_MEDIA_KEEP:-3} + 1)) | xargs -r rm -f
  fi
}

if [ "$1" = "--loop" ]; then
  while true; do
    one_backup || echo "$(date '+%F %T') backup FAILED"
    sleep $(( ${BACKUP_INTERVAL_HOURS:-24} * 3600 ))
  done
else
  one_backup
fi

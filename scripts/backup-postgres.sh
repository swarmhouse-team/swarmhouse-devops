#!/usr/bin/env bash
set -Eeuo pipefail

# --- Настройки ---
CONTAINER="postgres"
DB_NAME="$(docker exec "$CONTAINER" sh -ec 'printf "%s" "${POSTGRES_DB:?POSTGRES_DB не задана}"')"
KEEP=5

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_ROOT="${SCRIPT_DIR}/../data/backup"
STAMP="$(date +%Y-%m-%d_%H-%M-%S)"
TARGET="${BACKUP_ROOT}/${STAMP}"
TMP="${BACKUP_ROOT}/.tmp-${STAMP}"

log() { echo "[$(date '+%F %T')] $*"; }

# Не даём запуститься двум копиям одновременно
exec 9>"${SCRIPT_DIR}/.backup-postgres.lock"
flock -n 9 || { log "Бэкап уже выполняется, выходим"; exit 1; }

umask 077
mkdir -p "$BACKUP_ROOT"
chmod 700 "$BACKUP_ROOT"

# Если что-то упало — удалить незавершённую папку
trap 'rm -rf "$TMP"; log "ОШИБКА: бэкап не создан"' ERR

docker inspect -f '{{.State.Running}}' "$CONTAINER" | grep -qx true \
  || { log "Контейнер $CONTAINER не запущен"; exit 1; }

mkdir -p "$TMP"

log "Дамп базы ${DB_NAME}"
docker exec "$CONTAINER" sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$1" -Fc' _ "$DB_NAME" \
  > "${TMP}/${DB_NAME}.dump"

log "Дамп ролей"
docker exec "$CONTAINER" sh -c \
  'pg_dumpall -U "$POSTGRES_USER" --globals-only' \
  > "${TMP}/globals.sql"

log "Проверка дампа"
docker exec -i "$CONTAINER" pg_restore --list \
  < "${TMP}/${DB_NAME}.dump" > /dev/null

[ -s "${TMP}/${DB_NAME}.dump" ] || { log "Пустой дамп"; false; }

( cd "$TMP" && sha256sum ./* > SHA256SUMS )

# Папка появляется только после полностью успешного бэкапа
mv "$TMP" "$TARGET"
log "Готово: $TARGET ($(du -sh "$TARGET" | cut -f1))"

# Оставляем последние KEEP бэкапов
find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*' \
  | sort | head -n -"$KEEP" \
  | while read -r old; do
      log "Удаляю старый бэкап: $old"
      rm -rf -- "$old"
    done
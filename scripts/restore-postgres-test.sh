#!/usr/bin/env bash
set -Eeuo pipefail
shopt -s nullglob

CONTAINER="${POSTGRES_CONTAINER:-postgres}"

fail() {
  printf 'Ошибка: %s\n' "$*" >&2
  exit 1
}

if (( $# < 1 || $# > 2 )); then
  printf 'Использование: %s <папка_бэкапа> [restore_test_имя]\n' "$0" >&2
  exit 2
fi

BACKUP_DIR="$1"
TARGET_DB="${2:-restore_test_$(date +%Y%m%d_%H%M%S)}"

# Скрипт работает только с новыми базами с тестовым префиксом.
[[ "$TARGET_DB" =~ ^restore_test_[a-z0-9_]+$ ]] \
  || fail "Имя базы должно начинаться с restore_test_ и содержать только a-z, 0-9 и _"
(( ${#TARGET_DB} <= 63 )) || fail "Слишком длинное имя базы"

[[ -d "$BACKUP_DIR" ]] || fail "Папка не найдена: $BACKUP_DIR"
[[ -f "$BACKUP_DIR/SHA256SUMS" ]] || fail "Нет файла SHA256SUMS"

DUMPS=("$BACKUP_DIR"/*.dump)
(( ${#DUMPS[@]} == 1 )) || fail "В папке должен быть ровно один файл .dump"
DUMP_FILE="${DUMPS[0]}"
[[ -f "$DUMP_FILE" && -s "$DUMP_FILE" ]] || fail "Дамп отсутствует или пуст"

(
  cd -- "$BACKUP_DIR"
  sha256sum --strict -c SHA256SUMS
) || fail "Проверка контрольных сумм не прошла"

printf 'Создаю тестовую базу: %s\n' "$TARGET_DB"

docker exec "$CONTAINER" sh -ec '
  exec createdb -U "${POSTGRES_USER:?POSTGRES_USER не задан}" \
    --maintenance-db=postgres --template=template0 "$1"
' sh "$TARGET_DB" || fail "Не удалось создать тестовую базу. Возможно, она уже существует"

printf 'Восстанавливаю %s в %s\n' "$DUMP_FILE" "$TARGET_DB"

docker exec -i "$CONTAINER" sh -ec '
  exec pg_restore -U "${POSTGRES_USER:?POSTGRES_USER не задан}" \
    -d "$1" --single-transaction --verbose
' sh "$TARGET_DB" < "$DUMP_FILE" \
  || fail "Дамп не восстановлен. Тестовая база $TARGET_DB не удалена"

printf 'Восстановление завершено. Тестовая база: %s\n' "$TARGET_DB"
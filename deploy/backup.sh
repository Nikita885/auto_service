#!/usr/bin/env bash
# Снимок базы PostgreSQL. Запускается на ХОСТЕ по cron, не внутри контейнера.
#
#   10 3 * * * /opt/auto_service/deploy/backup.sh >> /var/log/autoservice-backup.log 2>&1
#
# Почему не «просто pg_dump»: база живёт в контейнере, на хосте клиента
# postgresql может не быть вовсе, а версии клиента и сервера обязаны
# совпадать по мажору. Поэтому дамп снимается тем же образом, что крутит
# базу, а наружу выводится через stdout.
#
# Формат custom (-Fc): сжат, восстанавливается выборочно через pg_restore и
# не зависит от порядка таблиц. Обычный SQL-текст пришлось бы сжимать
# отдельно и катить целиком.
#
# ВАЖНО: снимки лежат на том же диске, что и база. От случайного DROP и от
# порчи данных это спасает, от отказа диска — нет. Задайте BACKUP_REMOTE в
# .env (любая цель rsync: user@host:/path), и копия уедет за пределы
# сервера. Без этого бэкап считается наполовину сделанным.
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/auto_service}"
ENV_FILE="$PROJECT_DIR/.env"

# Читаем .env построчно, а не через `source`: в нём есть значения с
# пробелами и тире (COMPANY_WORKING_HOURS), и shell попытался бы их
# выполнить.
env_value() {
  [ -f "$ENV_FILE" ] || return 0
  sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1
}

DB_NAME="$(env_value POSTGRES_DB)";        DB_NAME="${DB_NAME:-autoservice}"
DB_USER="$(env_value POSTGRES_USER)";      DB_USER="${DB_USER:-autoservice}"
KEEP_DAYS="$(env_value BACKUP_KEEP_DAYS)"; KEEP_DAYS="${KEEP_DAYS:-14}"
BACKUP_DIR="$(env_value BACKUP_DIR)";      BACKUP_DIR="${BACKUP_DIR:-backups}"
REMOTE="$(env_value BACKUP_REMOTE)"

BACKUP_DIR="$PROJECT_DIR/$BACKUP_DIR"
COMPOSE=(docker compose -f "$PROJECT_DIR/docker-compose.yml" -f "$PROJECT_DIR/docker-compose.prod.yml")

mkdir -p "$BACKUP_DIR"

stamp="$(date -u +%Y%m%d-%H%M%S)"
target="$BACKUP_DIR/autoservice-$stamp.dump"
partial="$target.part"

# Пишем во временное имя: оборванный дамп не должен выглядеть как готовый
# снимок — иначе ротация однажды удалит последний целый, оставив мусор.
trap 'rm -f "$partial"' EXIT

echo "[backup] $(date -u +%FT%TZ) снимаем $DB_NAME"
"${COMPOSE[@]}" exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc > "$partial"

# Минимальная проверка целостности без лишних зависимостей: файл формата
# custom всегда начинается сигнатурой PGDMP. Пустой или обрезанный на
# первом килобайте дамп её не даст.
if [ "$(head -c 5 "$partial")" != "PGDMP" ]; then
  echo "[backup] ОШИБКА: в файле нет сигнатуры PGDMP, снимок негодный" >&2
  exit 1
fi

mv "$partial" "$target"
trap - EXIT
echo "[backup] готово: $target ($(du -h "$target" | cut -f1))"

# Ротация. Считаем по времени, а не по числу файлов: пропущенный день не
# должен сдвигать окно хранения.
deleted="$(find "$BACKUP_DIR" -maxdepth 1 -name 'autoservice-*.dump' -type f -mtime "+$KEEP_DAYS" -print -delete | wc -l)"
echo "[backup] удалено старше $KEEP_DAYS дней: $deleted"

# Копия за пределы сервера. Без неё отказ диска уносит и базу, и бэкапы.
if [ -n "$REMOTE" ]; then
  if command -v rsync > /dev/null; then
    rsync -a "$target" "$REMOTE/"
    echo "[backup] копия отправлена в $REMOTE"
  else
    echo "[backup] ВНИМАНИЕ: BACKUP_REMOTE задан, но rsync не установлен" >&2
    exit 1
  fi
else
  echo "[backup] ВНИМАНИЕ: BACKUP_REMOTE не задан, копия только на этом диске"
fi

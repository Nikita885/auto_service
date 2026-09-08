#!/usr/bin/env bash
set -euo pipefail

wait_for() {
  local host="$1" port="$2" name="$3"
  echo "[entrypoint] waiting for ${name} at ${host}:${port}..."
  until python -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(0 if s.connect_ex(('${host}', ${port}))==0 else 1)"; do
    sleep 1
  done
  echo "[entrypoint] ${name} is up"
}

wait_for "${POSTGRES_HOST:-db}" "${POSTGRES_PORT:-5432}" postgres
wait_for "redis" 6379 redis

case "${1:-api}" in
  api)
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput || true
    python manage.py bootstrap_demo || true
    exec daphne -b 0.0.0.0 -p 8000 config.asgi:application
    ;;
  worker)
    exec celery -A config worker -l info
    ;;
  beat)
    exec celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    ;;
  *)
    exec "$@"
    ;;
esac

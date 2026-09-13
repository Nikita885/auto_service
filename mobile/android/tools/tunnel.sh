#!/usr/bin/env bash
#
# Туннель к локальному серверу для тестов на телефоне.
#
# Зачем SSH, а не cloudflared: если на машине работает VPN, перехватывающий
# весь трафик (адаптеры с адресами 198.18.x.x), cloudflared не подключается —
# ему нужен либо UDP, либо прямой TLS до своих edge-серверов. SSH — обычный
# TCP-поток, он через такой VPN проходит.
#
# Бесплатные туннели выдают новое имя при каждом подключении и рвутся по
# таймауту, поэтому скрипт поднимает соединение заново и каждый раз печатает
# актуальный адрес. Менять его в приложении не требует пересборки: на экране
# входа отладочной сборки есть строка «Сервер: …».
#
#   bash tools/tunnel.sh            порт 8000
#   bash tools/tunnel.sh 9000       другой порт
#
set -u

PORT="${1:-8000}"
KEY="${HOME}/.ssh/id_ed25519"
URL_FILE="${TMPDIR:-/tmp}/autoservice-tunnel-url.txt"

# Ключ нужен localhost.run: без него сервис соединение принимает,
# но адрес не выдаёт.
if [ ! -f "$KEY" ]; then
    echo "Создаю SSH-ключ для туннеля: $KEY"
    ssh-keygen -t ed25519 -N "" -C "autoservice-tunnel" -f "$KEY" >/dev/null
fi

echo "Локальный сервер: http://localhost:${PORT}"
echo "Адрес туннеля дублируется в файл: ${URL_FILE}"
echo "Остановить: Ctrl+C"
echo

while true; do
    ssh -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o ServerAliveInterval=30 \
        -o ExitOnForwardFailure=yes \
        -i "$KEY" \
        -R "80:localhost:${PORT}" \
        nokey@localhost.run 2>&1 |
    while IFS= read -r line; do
        case "$line" in
            *lhr.life*)
                # В строке приходит готовый https-адрес — вытаскиваем и показываем.
                url=$(printf '%s\n' "$line" | grep -oE 'https://[a-z0-9.-]+\.lhr\.life' | head -1)
                if [ -n "$url" ]; then
                    printf '%s\n' "$url" > "$URL_FILE"
                    echo
                    echo "=================================================="
                    echo "  АДРЕС: $url"
                    echo "=================================================="
                    echo "  Впишите его в приложении: экран входа, строка"
                    echo "  «Сервер: …» внизу. Пересобирать APK не нужно."
                    echo
                fi
                ;;
        esac
    done

    echo "Туннель оборвался, переподключаюсь через 3 секунды…"
    sleep 3
done

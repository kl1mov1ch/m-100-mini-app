#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
domain="${1:?Укажите домен}"
email="${2:?Укажите email для сертификата}"
if [[ ! "$domain" =~ ^[A-Za-z0-9][A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]]; then
    printf '%s\n' 'Некорректный домен' >&2
    exit 1
fi
test -f deploy/.env.production
test -s deploy/secrets/telegram_bot_token
grep -Fxq "APP_ALLOWED_ORIGINS=https://$domain" deploy/.env.production
if [[ ! -f deploy/nginx.conf ]]; then
    cp deploy/nginx.http.conf deploy/nginx.conf
fi
mkdir -p deploy/certbot/www deploy/certbot/conf
docker compose up -d --no-deps nginx
docker compose --profile certificate run --rm certbot certonly --webroot -w /var/www/certbot --email "$email" --agree-tos --no-eff-email -d "$domain"
sed "s/APP_DOMAIN/$domain/g" deploy/nginx.https.conf.template > deploy/nginx.conf
docker compose up -d --build --wait app
docker compose exec -T nginx nginx -t
docker compose exec -T nginx nginx -s reload
curl --fail --retry 5 --retry-delay 2 "https://$domain/healthz"
printf 'HTTPS подготовлен: https://%s\n' "$domain"

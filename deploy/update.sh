#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only origin main
docker compose build app
docker compose up -d --wait app nginx
docker compose exec -T nginx nginx -t
docker compose exec -T nginx nginx -s reload
docker compose ps

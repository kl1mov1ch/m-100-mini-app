#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /var/miniApp/m-100
mkdir -p /var/backups/m100
APP_DATABASE=/var/miniApp/m-100/data/m100.sqlite3 .venv/bin/python scripts/data_archive.py backup "/var/backups/m100/m100-$(date -u +%Y%m%dT%H%M%SZ).zip"

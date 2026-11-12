#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /var/miniApp/m-100
mkdir -p /var/backups/m100
storage=$(.venv/bin/python - <<'PY'
from dotenv import dotenv_values
print(dotenv_values('deploy/secrets/app.env').get('APP_STORAGE', 'sqlite'))
PY
)
stamp=$(date -u +%Y%m%dT%H%M%SZ)
if test "$storage" = postgres; then
    target="/var/backups/m100/m100-$stamp.dump"
    temporary="$target.partial"
    trap 'rm -f -- "$temporary"' EXIT
    docker exec m100-postgres pg_dump -U m100_owner -d m100 -Fc > "$temporary"
    test -s "$temporary"
    docker exec -i m100-postgres pg_restore --list < "$temporary" > /dev/null
    mv -- "$temporary" "$target"
    directories=(imports)
    if test -d data/document-jobs; then directories+=(document-jobs); fi
    tar -czf "/var/backups/m100/m100-files-$stamp.tar.gz" -C data "${directories[@]}"
else
    APP_DATABASE=/var/miniApp/m-100/data/m100.sqlite3 .venv/bin/python scripts/data_archive.py backup "/var/backups/m100/m100-$stamp.zip"
fi

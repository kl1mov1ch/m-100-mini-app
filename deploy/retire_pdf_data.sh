#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
cd /var/miniApp/m-100

mode=${1:?Use archive or restore}
archive=${2:?Supply a /var/backups/m100/pdf-retired-* path}
case "$archive" in
    /var/backups/m100/pdf-retired-[0-9]*) ;;
    *) exit 2 ;;
esac
test "$(dirname -- "$archive")" = /var/backups/m100
files="$PWD/data/document-jobs"
tables=(registry.document_jobs registry.document_recognition_examples registry.document_work_rates)
psql() { docker exec -i m100-postgres psql -X -q -v ON_ERROR_STOP=1 -U m100_owner -d m100 "$@"; }
worker=$(systemctl show m100-document-worker.service -p ActiveState --value)
case "$worker" in
    inactive|failed) ;;
    *) printf 'Stop the PDF worker before changing its tables.\n' >&2; exit 1 ;;
esac

case "$mode" in
    archive)
        mkdir -- "$archive"
        args=()
        for table in "${tables[@]}"; do args+=(--table="$table"); done
        docker exec m100-postgres pg_dump -U m100_owner -d m100 -Fc "${args[@]}" > "$archive/schema.dump"
        docker exec -i m100-postgres pg_restore --list < "$archive/schema.dump" > "$archive/contents"
        for table in "${tables[@]}"; do grep -Fq "TABLE ${table/./ }" "$archive/contents"; done
        (cd "$archive"; sha256sum schema.dump > SHA256SUMS)
        if test -d "$files"; then mv -T -- "$files" "$archive/document-jobs"; fi
        if ! psql <<'SQL'
BEGIN;
DROP TABLE registry.document_jobs, registry.document_recognition_examples, registry.document_work_rates;
COMMIT;
SQL
        then
            if test -d "$archive/document-jobs"; then mv -T -- "$archive/document-jobs" "$files"; fi
            exit 1
        fi
        printf 'PDF archive created at %s\n' "$archive"
        ;;
    restore)
        test ! -e "$files"
        (cd "$archive"; sha256sum -c SHA256SUMS)
        docker exec -i m100-postgres pg_restore --single-transaction --exit-on-error -U m100_owner -d m100 < "$archive/schema.dump"
        if test -d "$archive/document-jobs"; then cp -a -- "$archive/document-jobs" "$files"; fi
        ;;
    *) exit 2 ;;
esac

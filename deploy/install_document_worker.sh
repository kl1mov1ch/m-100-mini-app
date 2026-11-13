#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for unit in service timer path; do
    install -o root -g root -m 644 "deploy/m100-document-worker.$unit" "/etc/systemd/system/m100-document-worker.$unit"
done
systemctl daemon-reload
systemctl reset-failed m100-document-worker.service
systemctl enable --now m100-document-worker.timer m100-document-worker.path
systemctl start --no-block m100-document-worker.service

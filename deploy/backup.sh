#!/usr/bin/env bash
# Nightly Postgres backup to local disk, keeping the last 14 days.
# Install on the VPS crontab:  0 3 * * *  /path/to/lazarus/deploy/backup.sh
set -euo pipefail
cd "$(dirname "$0")"

BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y-%m-%d)"

mkdir -p "$BACKUP_DIR"

docker compose -f docker-compose.yml -f docker-compose.prod.yml \
    exec -T postgres pg_dump -U "${POSTGRES_USER:-lazarus}" "${POSTGRES_DB:-lazarus}" \
    | gzip > "$BACKUP_DIR/lazarus-$STAMP.sql.gz"

find "$BACKUP_DIR" -name "lazarus-*.sql.gz" -mtime "+$KEEP_DAYS" -delete

echo "backup written: $BACKUP_DIR/lazarus-$STAMP.sql.gz"

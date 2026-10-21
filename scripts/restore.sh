#!/bin/sh
# Loads a dump made by backup-loop.sh or backup-now.sh into the running `db` service.
# Usage: scripts/restore.sh backups/vending-2026-10-21_18-00.sql.gz
set -eu
cd "$(dirname "$0")/.."
dump="${1:?path to a .sql.gz backup}"
docker compose stop bot worker api >/dev/null
gunzip -c "$dump" | docker compose exec -T db sh -c 'psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose up -d
echo "restored from $dump"

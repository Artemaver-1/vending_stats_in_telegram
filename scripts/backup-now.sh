#!/bin/sh
# Writes a fresh dump to ./backups on the host, e.g. right before moving to another computer.
set -eu
cd "$(dirname "$0")/.."
mkdir -p backups
file="backups/vending-$(date +%Y-%m-%d_%H-%M)-manual.sql.gz"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' | gzip > "$file"
echo "$file"

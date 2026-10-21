#!/bin/sh
# Runs inside the `backup` service: one dump right after start, then every 24 hours.
# The host is switched off now and then, so "on start" matters more than the schedule.
set -eu

KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"

while true; do
    file="/backups/vending-$(date +%Y-%m-%d_%H-%M).sql.gz"
    if pg_dump --clean --if-exists --no-owner | gzip > "$file.part"; then
        mv "$file.part" "$file"
        echo "backup written: $file"
    else
        rm -f "$file.part"
        echo "backup failed" >&2
    fi
    find /backups -name 'vending-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
    sleep 86400
done

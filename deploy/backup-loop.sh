#!/bin/sh
set -eu
umask 077
export PGPASSFILE=/tmp/mv-pgpass
printf 'db:5432:mv_signal:mv:%s\n' "$(cat /run/secrets/database_password)" > "$PGPASSFILE"
while true; do
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  target="/backups/mv-signal-$stamp.dump"
  if pg_dump -h db -U mv -d mv_signal -Fc --no-owner > "$target.partial"; then
    mv "$target.partial" "$target"
    sha256sum "$target" > "$target.sha256"
    printf '{"completed_at":"%s","file":"mv-signal-%s.dump"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$stamp" > /backup-status/last-success.partial
    chmod 644 /backup-status/last-success.partial
    mv /backup-status/last-success.partial /backup-status/last-success.json
    find /backups -maxdepth 1 -type f -name 'mv-signal-*.dump*' -mtime +13 -delete
    echo "Daily database backup completed: $stamp"
    sleep 86400
  else
    echo "Database backup failed; retrying in five minutes" >&2
    sleep 300
  fi
done

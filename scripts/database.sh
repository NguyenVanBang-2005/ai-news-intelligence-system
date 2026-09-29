#!/bin/sh
set -eu

# Run inside the Compose db container with: sh /ops/database.sh ...
action=${1:-}
filename=${2:-}
case "$filename" in
  ''|*[!a-zA-Z0-9._-]*|.*) echo 'Use a simple backup filename (no path).' >&2; exit 2 ;;
esac
archive="/backups/$filename"

case "$action" in
  backup)
    if [ -e "$archive" ]; then
      echo 'Backup already exists; choose a new filename.' >&2
      exit 2
    fi
    umask 077
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
      --format=custom --no-owner --no-acl --file="$archive"
    pg_restore --list "$archive" >/dev/null
    echo "Backup saved: $archive"
    ;;
  restore)
    target=${3:-}
    case "$target" in
      ''|*[!a-zA-Z0-9_]*|[0-9]*) echo 'Use a simple new database name.' >&2; exit 2 ;;
    esac
    if [ "$target" = "$POSTGRES_DB" ]; then
      echo 'Restore requires a separate new database.' >&2
      exit 2
    fi
    pg_restore --list "$archive" >/dev/null
    # createdb fails if the target exists, protecting existing data.
    createdb -U "$POSTGRES_USER" "$target"
    pg_restore -U "$POSTGRES_USER" -d "$target" --no-owner --no-acl \
      --exit-on-error --single-transaction "$archive"
    psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$target" \
      -c 'SELECT count(*) AS sources FROM sources' \
      -c 'SELECT count(*) AS articles FROM articles' \
      -c 'SELECT * FROM alembic_version'
    ;;
  *) echo 'Usage: database.sh backup FILE.dump | restore FILE.dump NEW_DATABASE' >&2; exit 2 ;;
esac

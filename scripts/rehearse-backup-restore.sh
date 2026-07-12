#!/usr/bin/env bash
set -euo pipefail

: "${TEST_DB_SUPERUSER_URL:?Set TEST_DB_SUPERUSER_URL to a disposable PostgreSQL superuser URL}"
source_db="novelwiki_rehearsal_source"
restore_db="novelwiki_rehearsal_restore"
root="$(cd "$(dirname "$0")/.." && pwd)"
artifact="$(mktemp -t tideglass-rehearsal-XXXXXX.dump)"
client_image="${POSTGRES_CLIENT_IMAGE:-postgres:18-alpine}"
cleanup() {
  rm -f "$artifact"
  uv run python "$root/tools/rehearsal_database.py" drop \
    --superuser-url "$TEST_DB_SUPERUSER_URL" --source "$source_db" --restore "$restore_db" >/dev/null 2>&1 || true
}
trap cleanup EXIT

case "$TEST_DB_SUPERUSER_URL" in
  *novelwiki_rehearsal_source*|*novelwiki_rehearsal_restore*)
    echo "Use a superuser maintenance URL, not a rehearsal database URL." >&2; exit 2 ;;
esac

client() {
  docker run --rm --network host -v "$artifact:/backup.dump" "$client_image" "$@"
}

uv run python "$root/tools/rehearsal_database.py" create \
  --superuser-url "$TEST_DB_SUPERUSER_URL" --source "$source_db" --restore "$restore_db"
source_url="$(uv run python "$root/tools/rehearsal_database.py" url --superuser-url "$TEST_DB_SUPERUSER_URL" --database "$source_db")"
restore_url="$(uv run python "$root/tools/rehearsal_database.py" url --superuser-url "$TEST_DB_SUPERUSER_URL" --database "$restore_db")"
DATABASE_URL="$source_url" DB_SUPERUSER_URL="$TEST_DB_SUPERUSER_URL" uv run python -c \
  'import asyncio; from novelwiki.db.schema import init_database; asyncio.run(init_database())'
uv run python "$root/tools/rehearsal_database.py" seed --database-url "$source_url"
client pg_dump --format=custom --no-owner --file=/backup.dump "$source_url"
client pg_restore --no-owner --dbname="$restore_url" /backup.dump
uv run python "$root/tools/rehearsal_database.py" verify --source-url "$source_url" --restore-url "$restore_url"
uv run python "$root/tools/rehearsal_database.py" drop \
  --superuser-url "$TEST_DB_SUPERUSER_URL" --source "$source_db" --restore "$restore_db"
echo "backup/restore rehearsal: ok"

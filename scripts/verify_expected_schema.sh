#!/usr/bin/env bash
set -Eeuo pipefail

if ! command -v psql >/dev/null 2>&1; then
  echo "psql is required but not installed or not on PATH" >&2
  exit 1
fi

DB_URL="${DATABASE_URL:-${MIGRATION_DATABASE_URL:-}}"

if [[ -z "$DB_URL" ]]; then
  echo "DATABASE_URL (or MIGRATION_DATABASE_URL) is required" >&2
  exit 1
fi

PSQL=(psql "$DB_URL" -v ON_ERROR_STOP=1 -X -tA)

check_column() {
  local table_name="$1"
  local column_name="$2"
  local exists
  exists="$("${PSQL[@]}" -c "select exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = '${table_name}' and column_name = '${column_name}');")"
  if [[ "$exists" != "t" ]]; then
    echo "Missing expected column: public.${table_name}.${column_name}" >&2
    exit 1
  fi
  echo "OK public.${table_name}.${column_name}"
}

check_table() {
  local table_name="$1"
  local exists
  exists="$("${PSQL[@]}" -c "select exists (select 1 from information_schema.tables where table_schema = 'public' and table_name = '${table_name}');")"
  if [[ "$exists" != "t" ]]; then
    echo "Missing expected table: public.${table_name}" >&2
    exit 1
  fi
  echo "OK public.${table_name}"
}

echo "Verifying backend-owned schema expectations"
check_table "schema_migrations"
check_table "pet_videos"
check_column "pet_videos" "final_url"
check_column "pet_videos" "provider_video_url"
check_column "pet_videos" "credit_cost"
check_column "pet_videos" "plan_tier"
check_column "pet_videos" "routing_quality"

echo "Schema verification complete"

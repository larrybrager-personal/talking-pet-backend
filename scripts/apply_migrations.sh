#!/usr/bin/env bash
set -Eeuo pipefail

if ! command -v psql >/dev/null 2>&1; then
  echo "psql is required but not installed or not on PATH" >&2
  exit 1
fi

DB_URL="${DATABASE_URL:-${MIGRATION_DATABASE_URL:-}}"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-migrations}"
TARGET_ENV="${TARGET_ENV:-unspecified}"
DRY_RUN="${DRY_RUN:-false}"

if [[ -z "$DB_URL" ]]; then
  echo "DATABASE_URL (or MIGRATION_DATABASE_URL) is required" >&2
  exit 1
fi

if [[ ! -d "$MIGRATIONS_DIR" ]]; then
  echo "Migrations directory not found: $MIGRATIONS_DIR" >&2
  exit 1
fi

shopt -s nullglob
migration_files=("$MIGRATIONS_DIR"/*.sql)
shopt -u nullglob

if [[ ${#migration_files[@]} -eq 0 ]]; then
  echo "No SQL migration files found in $MIGRATIONS_DIR"
  exit 0
fi

PSQL=(psql "$DB_URL" -v ON_ERROR_STOP=1 -X)

"${PSQL[@]}" <<'SQL'
create table if not exists public.schema_migrations (
  filename text primary key,
  checksum_sha256 text not null,
  applied_at timestamptz not null default now()
);
SQL

echo "Applying migrations for TARGET_ENV=$TARGET_ENV from $MIGRATIONS_DIR"

for file in "${migration_files[@]}"; do
  filename="$(basename "$file")"
  checksum="$(shasum -a 256 "$file" | awk '{print $1}')"
  existing_checksum="$("${PSQL[@]}" -tAqc "select checksum_sha256 from public.schema_migrations where filename = '$filename'")"

  if [[ -n "$existing_checksum" ]]; then
    if [[ "$existing_checksum" != "$checksum" ]]; then
      echo "Refusing to continue: migration $filename was already applied with a different checksum." >&2
      echo "Create a new migration file instead of editing an applied one." >&2
      exit 1
    fi

    echo "Skipping already-applied migration: $filename"
    continue
  fi

  echo "Applying migration: $filename"

  if [[ "$DRY_RUN" == "true" ]]; then
    echo "DRY_RUN=true -> would apply $filename"
    continue
  fi

  "${PSQL[@]}" \
    -c "begin" \
    -f "$file" \
    -c "insert into public.schema_migrations (filename, checksum_sha256) values ('$filename', '$checksum')" \
    -c "commit"
done

echo "Migration run complete"

#!/usr/bin/env bash
set -eu

CSOL_APP_PASSWORD="$(cat /run/secrets/postgres_app_password)"
if [ -z "$CSOL_APP_PASSWORD" ]; then
    echo "The postgres_app_password secret must be nonempty" >&2
    exit 1
fi
export CSOL_APP_PASSWORD

psql -X -w --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --set=ON_ERROR_STOP=1 --single-transaction \
    --file=- --file=/usr/local/share/csol/migrations/001_initial.sql <<'SQL'
\getenv app_password CSOL_APP_PASSWORD
CREATE ROLE csol_app LOGIN PASSWORD :'app_password';
REVOKE ALL ON DATABASE csol FROM PUBLIC;
GRANT CONNECT ON DATABASE csol TO csol_app;
SQL

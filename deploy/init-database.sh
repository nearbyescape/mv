#!/bin/sh
set -eu
export MV_APP_PASSWORD="$(cat /run/secrets/database_password)"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv mv_app_password MV_APP_PASSWORD
CREATE ROLE mv LOGIN PASSWORD :'mv_app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER DATABASE mv_signal OWNER TO mv;
ALTER SCHEMA public OWNER TO mv;
SQL
unset MV_APP_PASSWORD

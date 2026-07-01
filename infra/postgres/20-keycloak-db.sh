#!/bin/bash
# initdb-time wiring that cannot live in plain SQL because it reads secrets:
#  - dedicated Keycloak database + login role
#  - passwords for the least-privilege login roles created by 10-roles.sql
# All passwords come from compose secrets (never the repo).
set -euo pipefail

KC_DB_PW="$(cat /run/secrets/kc_db_pw)"
APP_DB_PW="$(cat /run/secrets/app_db_pw)"
CONSOLIDATOR_DB_PW="$(cat /run/secrets/consolidator_db_pw)"
EVAL_DB_PW="$(cat /run/secrets/eval_db_pw)"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
    CREATE ROLE keycloak LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD '$KC_DB_PW';
    CREATE DATABASE keycloak OWNER keycloak;
    REVOKE ALL ON DATABASE keycloak FROM PUBLIC;

    ALTER ROLE app_user          PASSWORD '$APP_DB_PW';
    ALTER ROLE consolidator_user PASSWORD '$CONSOLIDATOR_DB_PW';
    ALTER ROLE eval_user         PASSWORD '$EVAL_DB_PW';
EOSQL

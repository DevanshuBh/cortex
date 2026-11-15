-- Runs once as the superuser when the Postgres volume is created.
-- cortex_owner owns the schema and runs migrations; cortex_app is what the API and workers use.
-- Neither is a superuser, and cortex_app cannot bypass row-level security.
CREATE ROLE cortex_owner LOGIN PASSWORD 'cortex_owner' NOSUPERUSER NOCREATEROLE NOBYPASSRLS;
CREATE ROLE cortex_app   LOGIN PASSWORD 'cortex_app'   NOSUPERUSER NOCREATEROLE NOBYPASSRLS;

CREATE DATABASE cortex OWNER cortex_owner;
\connect cortex
CREATE EXTENSION IF NOT EXISTS vector;
ALTER SCHEMA public OWNER TO cortex_owner;
GRANT USAGE ON SCHEMA public TO cortex_app;
ALTER DEFAULT PRIVILEGES FOR ROLE cortex_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cortex_app;
ALTER DEFAULT PRIVILEGES FOR ROLE cortex_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO cortex_app;

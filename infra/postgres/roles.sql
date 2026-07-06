-- Mnemosyne — Postgres role separation under FORCE RLS (security must-do).
-- Runs at init. Closes the "single superuser DSN silently bypasses FORCE RLS" gap.
-- App services connect with LEAST-PRIVILEGE roles; only the consolidator may write/destroy.
--
-- An ops-check MUST live-probe each prod DSN:
--   SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user;
-- and FAIL if either is true.

-- Edge/API role: read + non-destructive writes, NOSUPERUSER, NOBYPASSRLS, no DELETE/TRUNCATE.
CREATE ROLE mnemosyne_app NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

-- Consolidator: the SOLE write/destructive authority (R7 consolidator-only writes).
CREATE ROLE mnemosyne_consolidator NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

-- Eval / metrics: SELECT-only.
CREATE ROLE mnemosyne_readonly NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

-- Login users map onto the above (passwords/certs supplied out-of-band, e.g. Vault dynamic creds).
CREATE ROLE app_user           LOGIN IN ROLE mnemosyne_app;
CREATE ROLE consolidator_user  LOGIN IN ROLE mnemosyne_consolidator;
CREATE ROLE eval_user          LOGIN IN ROLE mnemosyne_readonly;

-- Default privileges (tighten per schema once tables exist):
--   GRANT SELECT, INSERT, UPDATE ON <tables> TO mnemosyne_app;          -- no DELETE/TRUNCATE
--   GRANT SELECT, INSERT, UPDATE, DELETE ON <tables> TO mnemosyne_consolidator;
--   GRANT SELECT ON <tables> TO mnemosyne_readonly;
-- And on every tenant-scoped table:
--   ALTER TABLE <t> ENABLE ROW LEVEL SECURITY;
--   ALTER TABLE <t> FORCE ROW LEVEL SECURITY;             -- applies even to the table owner
--   CREATE POLICY tenant_isolation ON <t> USING (tenant_id = current_setting('mnemosyne.tenant_id')::uuid);
-- tenant_id is set per request via SET LOCAL from the VERIFIED session claim only.

REVOKE ALL ON DATABASE mnemosyne FROM PUBLIC;

-- ---------------------------------------------------------------------------
-- Concrete grants. In the prod compose, sql/schema.sql runs FIRST (mounted as
-- /docker-entrypoint-initdb.d/05-schema.sql), so the 24 tables exist here.
-- ---------------------------------------------------------------------------
GRANT CONNECT ON DATABASE mnemosyne TO mnemosyne_app, mnemosyne_consolidator, mnemosyne_readonly;
GRANT USAGE ON SCHEMA public TO mnemosyne_app, mnemosyne_consolidator, mnemosyne_readonly;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO mnemosyne_app;            -- no DELETE/TRUNCATE
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO mnemosyne_consolidator;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO mnemosyne_readonly;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mnemosyne_app, mnemosyne_consolidator;

-- The engine ensures/ALTERs its schema at connection time (runtime side-state
-- AND domain-table column ensures), so the app group must own the tables.
-- FORCE RLS binds owners too, so tenant isolation holds; DELETE/TRUNCATE are
-- explicitly revoked from the app group below (residual: an owner could
-- re-grant itself — the hard delete boundary remains RLS + the capability layer).
GRANT CREATE ON SCHEMA public TO mnemosyne_app, mnemosyne_consolidator;
GRANT mnemosyne_app TO consolidator_user;   -- consolidator manages runtime side-state too
DO $$
DECLARE t record;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP
    EXECUTE format('ALTER TABLE public.%I OWNER TO mnemosyne_app', t.tablename);
  END LOOP;
END $$;
REVOKE DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM mnemosyne_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO mnemosyne_consolidator;
-- FK cascade deletes (consolidate_evidence -> justifications/contradictions)
-- execute as the TABLE OWNER (mnemosyne_app), whose DELETE was just revoked, so
-- the owner needs a narrow DELETE re-grant on exactly those two cascade targets.
-- The hard-delete boundary stays RLS + the capability layer; app DELETE remains
-- revoked everywhere else.
GRANT DELETE ON justifications, contradictions TO mnemosyne_app;
-- Audit rows are append-only even for write-capable runtime roles; schema.sql
-- installs the BEFORE UPDATE/DELETE trigger that enforces this at execution.
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM mnemosyne_app, mnemosyne_consolidator;
GRANT SELECT, INSERT ON audit_log TO mnemosyne_app, mnemosyne_consolidator;

-- Tables created at runtime by one login role stay usable by the other.
ALTER DEFAULT PRIVILEGES FOR ROLE app_user IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mnemosyne_consolidator;
ALTER DEFAULT PRIVILEGES FOR ROLE app_user IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE ON TABLES TO mnemosyne_app;
ALTER DEFAULT PRIVILEGES FOR ROLE consolidator_user IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE ON TABLES TO mnemosyne_app;
ALTER DEFAULT PRIVILEGES FOR ROLE consolidator_user IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mnemosyne_consolidator;

-- Engine schema-ensure creates new tables at runtime as the connected app role
-- (mnemosyne_app members own them). "GRANT ... ON ALL TABLES" above only covers
-- tables that exist at init, so later-created tables (e.g. justifications)
-- silently lacked consolidator DELETE and broke TMS supersession pruning in
-- production. Default privileges make future engine-created tables inherit the
-- same posture; the audit_log append-only revocation above remains named and
-- explicit.
ALTER DEFAULT PRIVILEGES FOR ROLE mnemosyne_app IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mnemosyne_consolidator;
ALTER DEFAULT PRIVILEGES FOR ROLE mnemosyne_app IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE ON TABLES TO mnemosyne_app;

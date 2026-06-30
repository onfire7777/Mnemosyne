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

-- Mnemosyne canonical PostgreSQL schema.
-- Source: Mnemosyne-v2-Build-Blueprint.md, Part VI section 29 and Appendix A.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS tenants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS branches (
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL DEFAULT 'main',
  from_branch TEXT,
  kind TEXT NOT NULL DEFAULT 'scratch',
  head BYTEA,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS evidence (
  cid BYTEA NOT NULL,
  branch TEXT NOT NULL DEFAULT 'main',
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id UUID NOT NULL,
  session_id UUID,
  actor TEXT NOT NULL CHECK (actor IN ('user', 'assistant', 'tool', 'system', 'external')),
  source_type TEXT NOT NULL,
  source_identity TEXT,
  content TEXT,
  content_pointer TEXT,
  modality TEXT NOT NULL DEFAULT 'text',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  trust_tier SMALLINT NOT NULL DEFAULT 0,
  capability_tags TEXT[] NOT NULL DEFAULT '{}',
  sensitivity SMALLINT NOT NULL DEFAULT 0,
  signed_provenance JSONB,
  access_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  embedding VECTOR(1024),
  embedding_partition TEXT NOT NULL DEFAULT 'none' CHECK (embedding_partition IN ('public', 'private', 'none')),
  lexeme TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', coalesce(content, ''))) STORED,
  erased BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, branch, cid),
  FOREIGN KEY (tenant_id, branch) REFERENCES branches(tenant_id, name)
);

CREATE INDEX IF NOT EXISTS evidence_embedding_public_hnsw ON evidence USING hnsw (embedding vector_cosine_ops) WHERE embedding_partition = 'public';
CREATE INDEX IF NOT EXISTS evidence_embedding_private_hnsw ON evidence USING hnsw (embedding vector_cosine_ops) WHERE embedding_partition = 'private';
CREATE INDEX IF NOT EXISTS evidence_embedding_none_btree ON evidence (tenant_id, branch, created_at DESC, cid) WHERE embedding_partition = 'none';
CREATE INDEX IF NOT EXISTS evidence_null_embedding_fallback_idx ON evidence (tenant_id, branch, created_at DESC, cid) WHERE embedding IS NULL AND embedding_partition <> 'none' AND erased = false;
CREATE INDEX IF NOT EXISTS evidence_lexeme_gin ON evidence USING gin (lexeme);

CREATE TABLE IF NOT EXISTS assertions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id UUID,
  branch TEXT NOT NULL DEFAULT 'main',
  subject TEXT NOT NULL,
  predicate TEXT NOT NULL,
  object TEXT NOT NULL,
  scope JSONB NOT NULL DEFAULT '{}'::jsonb,
  confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  calibration JSONB NOT NULL DEFAULT '{}'::jsonb,
  calibrated_confidence REAL CHECK (calibrated_confidence IS NULL OR (calibrated_confidence >= 0 AND calibrated_confidence <= 1)),
  salience REAL NOT NULL DEFAULT 0.5,
  valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_to TIMESTAMPTZ,
  transaction_time TIMESTAMPTZ NOT NULL DEFAULT now(),
  recorded_time TIMESTAMPTZ NOT NULL DEFAULT now(),
  expired_at TIMESTAMPTZ,
  justification_id UUID,
  source_evidence_cids BYTEA[] NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate', 'active', 'superseded', 'contested', 'quarantined', 'retracted')),
  version INT NOT NULL DEFAULT 1,
  superseded_by UUID,
  trust_tier SMALLINT NOT NULL DEFAULT 0,
  sensitivity SMALLINT NOT NULL DEFAULT 0,
  access_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  embedding VECTOR(1024),
  embedding_partition TEXT NOT NULL DEFAULT 'none' CHECK (embedding_partition IN ('public', 'private', 'none')),
  lexeme TSVECTOR,
  last_accessed TIMESTAMPTZ,
  access_count INT NOT NULL DEFAULT 0,
  FOREIGN KEY (tenant_id, branch) REFERENCES branches(tenant_id, name),
  CHECK (valid_to IS NULL OR valid_to > valid_from)
);

CREATE INDEX IF NOT EXISTS assertions_embedding_public_hnsw ON assertions USING hnsw (embedding vector_cosine_ops) WHERE embedding_partition = 'public';
CREATE INDEX IF NOT EXISTS assertions_embedding_private_hnsw ON assertions USING hnsw (embedding vector_cosine_ops) WHERE embedding_partition = 'private';
CREATE INDEX IF NOT EXISTS assertions_embedding_none_btree ON assertions (tenant_id, branch, status, valid_from DESC, id) WHERE embedding_partition = 'none';
CREATE INDEX IF NOT EXISTS assertions_lexeme_gin ON assertions USING gin (lexeme);
CREATE INDEX IF NOT EXISTS assertions_current ON assertions (tenant_id, subject, predicate, branch, status, valid_from DESC);

CREATE TABLE IF NOT EXISTS justifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  assertion_id UUID REFERENCES assertions(id) ON DELETE CASCADE,
  evidence_cids BYTEA[] NOT NULL DEFAULT '{}',
  rule TEXT,
  dependency_ids UUID[] NOT NULL DEFAULT '{}',
  kind TEXT NOT NULL DEFAULT 'support',
  label JSONB NOT NULL DEFAULT '{}'::jsonb,
  hypothesis_prob REAL CHECK (hypothesis_prob IS NULL OR (hypothesis_prob >= 0 AND hypothesis_prob <= 1))
);

CREATE TABLE IF NOT EXISTS entities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  canonical TEXT NOT NULL,
  type TEXT NOT NULL DEFAULT 'unknown',
  summary TEXT,
  salience REAL NOT NULL DEFAULT 0.5,
  embedding VECTOR(1024),
  source_evidence_cids BYTEA[] NOT NULL DEFAULT '{}',
  access_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE entities ADD COLUMN IF NOT EXISTS source_evidence_cids BYTEA[] NOT NULL DEFAULT '{}';
ALTER TABLE entities ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE UNIQUE INDEX IF NOT EXISTS entities_tenant_canonical_unique ON entities (tenant_id, canonical);

CREATE TABLE IF NOT EXISTS entity_aliases (
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  alias TEXT NOT NULL,
  entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  PRIMARY KEY (tenant_id, alias)
);

CREATE TABLE IF NOT EXISTS relations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  branch TEXT NOT NULL DEFAULT 'main',
  source TEXT NOT NULL,
  predicate TEXT NOT NULL,
  target TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.7 CHECK (confidence >= 0 AND confidence <= 1),
  weight REAL NOT NULL DEFAULT 1.0,
  valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_to TIMESTAMPTZ,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expired_at TIMESTAMPTZ,
  justification_id UUID,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded', 'retracted')),
  source_evidence_cids BYTEA[] NOT NULL DEFAULT '{}',
  access_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  FOREIGN KEY (tenant_id, branch) REFERENCES branches(tenant_id, name),
  CHECK (valid_to IS NULL OR valid_to > valid_from)
);

CREATE TABLE IF NOT EXISTS graph_ppr_cache (
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  branch TEXT NOT NULL DEFAULT 'main',
  seed_hash TEXT NOT NULL,
  as_of_key TEXT NOT NULL,
  as_of TIMESTAMPTZ,
  relation_fingerprint TEXT NOT NULL,
  cache_depth INTEGER NOT NULL DEFAULT 0 CHECK (cache_depth >= 0),
  hits JSONB NOT NULL DEFAULT '[]'::jsonb,
  refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, branch, seed_hash, as_of_key),
  FOREIGN KEY (tenant_id, branch) REFERENCES branches(tenant_id, name)
);

CREATE TABLE IF NOT EXISTS contradictions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  a UUID NOT NULL REFERENCES assertions(id) ON DELETE CASCADE,
  b UUID NOT NULL REFERENCES assertions(id) ON DELETE CASCADE,
  detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  status TEXT NOT NULL DEFAULT 'open',
  resolution TEXT
);

CREATE TABLE IF NOT EXISTS procedures (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  body TEXT NOT NULL,
  signature JSONB NOT NULL DEFAULT '{}'::jsonb,
  embedding VECTOR(1024),
  status TEXT NOT NULL DEFAULT 'candidate',
  version INT NOT NULL DEFAULT 1,
  superseded_by UUID,
  success_rate REAL,
  n_trials INT NOT NULL DEFAULT 0,
  validated_by UUID,
  source_evidence_cids BYTEA[] NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS lessons (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id UUID,
  lesson_type TEXT NOT NULL,
  failure_signature TEXT,
  content TEXT NOT NULL,
  votes INT NOT NULL DEFAULT 2,
  status TEXT NOT NULL DEFAULT 'candidate',
  source_evidence_cids BYTEA[] NOT NULL DEFAULT '{}',
  embedding VECTOR(1024)
);

CREATE TABLE IF NOT EXISTS preferences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id UUID NOT NULL,
  category TEXT NOT NULL CHECK (category IN ('format', 'tone', 'workflow', 'tooling', 'domain', 'constraint')),
  statement TEXT NOT NULL,
  scope JSONB NOT NULL DEFAULT '{}'::jsonb,
  confidence REAL NOT NULL DEFAULT 0.7 CHECK (confidence >= 0 AND confidence <= 1),
  explicit BOOLEAN NOT NULL DEFAULT false,
  exceptions JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_evidence_cids BYTEA[] NOT NULL DEFAULT '{}',
  access_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_to TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'active',
  superseded_by UUID
);

CREATE TABLE IF NOT EXISTS user_latent (
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id UUID NOT NULL,
  embedding VECTOR(1024),
  summary TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, user_id)
);

CREATE TABLE IF NOT EXISTS trajectories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id UUID,
  session_id UUID,
  task TEXT NOT NULL,
  steps JSONB NOT NULL DEFAULT '[]'::jsonb,
  outcome TEXT,
  reward REAL,
  memory_version BYTEA,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS self_model (
  id BIGSERIAL PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  metric TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  value REAL NOT NULL,
  metric_window TSTZRANGE NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_cases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  origin TEXT NOT NULL,
  signature TEXT NOT NULL,
  query TEXT NOT NULL,
  expected JSONB NOT NULL,
  tier TEXT NOT NULL DEFAULT 'smoke',
  protected BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS resources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  uri TEXT NOT NULL,
  version INT NOT NULL DEFAULT 1,
  content_hash BYTEA,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  access_policy JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS merges (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  frm TEXT NOT NULL,
  into_ TEXT NOT NULL,
  report JSONB NOT NULL,
  at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS deletion_log (
  id BIGSERIAL PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  evidence_cid BYTEA NOT NULL,
  requested_by TEXT NOT NULL,
  propagated JSONB NOT NULL,
  at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS conformal_calibration (
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  memory_type TEXT NOT NULL,
  scores REAL[] NOT NULL DEFAULT '{}',
  target_coverage REAL NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, memory_type)
);

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY,
  tenant_id UUID,
  actor TEXT,
  op TEXT NOT NULL,
  target_id UUID,
  trust_tier SMALLINT,
  capability_tags TEXT[] NOT NULL DEFAULT '{}',
  diff JSONB NOT NULL DEFAULT '{}'::jsonb,
  at TIMESTAMPTZ NOT NULL DEFAULT now(),
  event_id TEXT
);

ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS event_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS audit_log_tenant_event_unique
  ON audit_log(tenant_id, event_id)
  WHERE event_id IS NOT NULL;

CREATE OR REPLACE FUNCTION mnemosyne_audit_log_append_only()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_log is append-only; % is not allowed', TG_OP
    USING ERRCODE = '42501';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log;
CREATE TRIGGER audit_log_append_only
  BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION mnemosyne_audit_log_append_only();

CREATE TABLE IF NOT EXISTS runtime_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'retry', 'complete', 'dead')),
  attempts INT NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  max_attempts INT NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
  last_error TEXT,
  result JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS runtime_jobs_tenant_status_kind_idx
  ON runtime_jobs(tenant_id, status, kind, created_at);

CREATE TABLE IF NOT EXISTS runtime_state (
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, key)
);

-- Working memory is transient, but it is still durable enough to survive a
-- request boundary. External ids remain lossless while tenant/session/item is
-- the composite identity used by the engine. Provenance is checked by the
-- write/read paths against evidence; no implicit promotion foreign key exists.
CREATE TABLE IF NOT EXISTS working_memory (
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  session_id UUID NOT NULL,
  external_session_id TEXT NOT NULL,
  item_id TEXT NOT NULL,
  user_id UUID NOT NULL,
  external_user_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  task_id TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  trust_tier SMALLINT NOT NULL DEFAULT 0,
  capability_tags TEXT[] NOT NULL DEFAULT '{}',
  sensitivity SMALLINT NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'expired')),
  expired_at TIMESTAMPTZ,
  evidence_ids BYTEA[] NOT NULL DEFAULT '{}',
  access_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (tenant_id, session_id, item_id),
  CHECK (expires_at > created_at),
  CHECK (expires_at <= created_at + interval '24 hours')
);

CREATE INDEX IF NOT EXISTS working_memory_scope_created_idx
  ON working_memory(tenant_id, session_id, status, created_at DESC, item_id);
CREATE INDEX IF NOT EXISTS working_memory_expiry_idx
  ON working_memory(tenant_id, status, expires_at, external_session_id, item_id)
  WHERE status = 'active';

CREATE OR REPLACE FUNCTION mnemosyne_current_tenant()
RETURNS UUID
LANGUAGE sql
STABLE
AS $$
  SELECT nullif(current_setting('mnemosyne.tenant_id', true), '')::uuid
$$;

ALTER TABLE branches ENABLE ROW LEVEL SECURITY;
ALTER TABLE branches FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS branches_tenant_isolation ON branches;
CREATE POLICY branches_tenant_isolation ON branches
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS evidence_tenant_isolation ON evidence;
CREATE POLICY evidence_tenant_isolation ON evidence
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE assertions ENABLE ROW LEVEL SECURITY;
ALTER TABLE assertions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS assertions_tenant_isolation ON assertions;
CREATE POLICY assertions_tenant_isolation ON assertions
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE justifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE justifications FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS justifications_tenant_isolation ON justifications;
CREATE POLICY justifications_tenant_isolation ON justifications
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE entities FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS entities_tenant_isolation ON entities;
CREATE POLICY entities_tenant_isolation ON entities
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE entity_aliases ENABLE ROW LEVEL SECURITY;
ALTER TABLE entity_aliases FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS entity_aliases_tenant_isolation ON entity_aliases;
CREATE POLICY entity_aliases_tenant_isolation ON entity_aliases
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE relations ENABLE ROW LEVEL SECURITY;
ALTER TABLE relations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS relations_tenant_isolation ON relations;
CREATE POLICY relations_tenant_isolation ON relations
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE graph_ppr_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE graph_ppr_cache FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS graph_ppr_cache_tenant_isolation ON graph_ppr_cache;
CREATE POLICY graph_ppr_cache_tenant_isolation ON graph_ppr_cache
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE contradictions ENABLE ROW LEVEL SECURITY;
ALTER TABLE contradictions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS contradictions_tenant_isolation ON contradictions;
CREATE POLICY contradictions_tenant_isolation ON contradictions
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE procedures ENABLE ROW LEVEL SECURITY;
ALTER TABLE procedures FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS procedures_tenant_isolation ON procedures;
CREATE POLICY procedures_tenant_isolation ON procedures
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE lessons ENABLE ROW LEVEL SECURITY;
ALTER TABLE lessons FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS lessons_tenant_isolation ON lessons;
CREATE POLICY lessons_tenant_isolation ON lessons
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE preferences FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS preferences_tenant_isolation ON preferences;
CREATE POLICY preferences_tenant_isolation ON preferences
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE user_latent ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_latent FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_latent_tenant_isolation ON user_latent;
CREATE POLICY user_latent_tenant_isolation ON user_latent
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE trajectories ENABLE ROW LEVEL SECURITY;
ALTER TABLE trajectories FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS trajectories_tenant_isolation ON trajectories;
CREATE POLICY trajectories_tenant_isolation ON trajectories
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE self_model ENABLE ROW LEVEL SECURITY;
ALTER TABLE self_model FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS self_model_tenant_isolation ON self_model;
CREATE POLICY self_model_tenant_isolation ON self_model
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE eval_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE eval_cases FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS eval_cases_tenant_isolation ON eval_cases;
CREATE POLICY eval_cases_tenant_isolation ON eval_cases
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE resources ENABLE ROW LEVEL SECURITY;
ALTER TABLE resources FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS resources_tenant_isolation ON resources;
CREATE POLICY resources_tenant_isolation ON resources
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE merges ENABLE ROW LEVEL SECURITY;
ALTER TABLE merges FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS merges_tenant_isolation ON merges;
CREATE POLICY merges_tenant_isolation ON merges
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE deletion_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE deletion_log FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS deletion_log_tenant_isolation ON deletion_log;
CREATE POLICY deletion_log_tenant_isolation ON deletion_log
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE conformal_calibration ENABLE ROW LEVEL SECURITY;
ALTER TABLE conformal_calibration FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS conformal_calibration_tenant_isolation ON conformal_calibration;
CREATE POLICY conformal_calibration_tenant_isolation ON conformal_calibration
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS audit_log_tenant_isolation ON audit_log;
CREATE POLICY audit_log_tenant_isolation ON audit_log
  USING (tenant_id IS NULL OR tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id IS NULL OR tenant_id = mnemosyne_current_tenant());

ALTER TABLE runtime_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime_jobs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS runtime_jobs_tenant_isolation ON runtime_jobs;
CREATE POLICY runtime_jobs_tenant_isolation ON runtime_jobs
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE runtime_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime_state FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS runtime_state_tenant_isolation ON runtime_state;
CREATE POLICY runtime_state_tenant_isolation ON runtime_state
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

ALTER TABLE working_memory ENABLE ROW LEVEL SECURITY;
ALTER TABLE working_memory FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS working_memory_tenant_isolation ON working_memory;
CREATE POLICY working_memory_tenant_isolation ON working_memory
  USING (tenant_id = mnemosyne_current_tenant())
  WITH CHECK (tenant_id = mnemosyne_current_tenant());

-- ===========================================================================
-- Additive blueprint-parity columns (idempotent migration).
-- These are declared inline in the CREATE TABLE statements above for fresh
-- loads; the ADD COLUMN IF NOT EXISTS statements below bring pre-existing
-- deployments up to the canonical structure without a full reload. They are
-- additive-only (nullable or defaulted), so existing rows and the engine's
-- row->model converters (which read columns explicitly) are unaffected.
-- Rollback is a corresponding DROP COLUMN; no data is destroyed by adding.
-- ===========================================================================

-- assertions: I4 activation salience, I8 calibrated confidence, explicit recorded (transaction) time.
ALTER TABLE assertions ADD COLUMN IF NOT EXISTS salience REAL NOT NULL DEFAULT 0.5;
ALTER TABLE assertions ADD COLUMN IF NOT EXISTS calibrated_confidence REAL
  CHECK (calibrated_confidence IS NULL OR (calibrated_confidence >= 0 AND calibrated_confidence <= 1));
ALTER TABLE assertions ADD COLUMN IF NOT EXISTS recorded_time TIMESTAMPTZ NOT NULL DEFAULT now();

-- relations: edge weight, bitemporal recorded/expired time, belief-core link, lifecycle status.
ALTER TABLE relations ADD COLUMN IF NOT EXISTS weight REAL NOT NULL DEFAULT 1.0;
ALTER TABLE relations ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE relations ADD COLUMN IF NOT EXISTS expired_at TIMESTAMPTZ;
ALTER TABLE relations ADD COLUMN IF NOT EXISTS justification_id UUID;
ALTER TABLE relations ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'
  CHECK (status IN ('active', 'superseded', 'retracted'));

CREATE TABLE IF NOT EXISTS graph_ppr_cache (
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  branch TEXT NOT NULL DEFAULT 'main',
  seed_hash TEXT NOT NULL,
  as_of_key TEXT NOT NULL,
  as_of TIMESTAMPTZ,
  relation_fingerprint TEXT NOT NULL,
  cache_depth INTEGER NOT NULL DEFAULT 0 CHECK (cache_depth >= 0),
  hits JSONB NOT NULL DEFAULT '[]'::jsonb,
  refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, branch, seed_hash, as_of_key),
  FOREIGN KEY (tenant_id, branch) REFERENCES branches(tenant_id, name)
);

-- preferences: supersession pointer for revised preferences.
ALTER TABLE preferences ADD COLUMN IF NOT EXISTS superseded_by UUID;

-- evidence: stored lexical tsvector (mirrors assertions.lexeme) + GIN index so
-- full-text search stops recomputing to_tsvector('english', content) per row
-- at query time. GENERATED ALWAYS pins the column to exactly the prior
-- query-time expression, keeping ranking inputs byte-identical; the engine
-- also applies this idempotently at runtime (_ensure_evidence_lexeme_schema).
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS lexeme TSVECTOR
  GENERATED ALWAYS AS (to_tsvector('english', coalesce(content, ''))) STORED;
CREATE INDEX IF NOT EXISTS evidence_lexeme_gin ON evidence USING gin (lexeme);

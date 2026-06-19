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
  trust_tier SMALLINT NOT NULL DEFAULT 1,
  capability_tags TEXT[] NOT NULL DEFAULT '{}',
  sensitivity SMALLINT NOT NULL DEFAULT 0,
  signed_provenance JSONB,
  access_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  erased BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, branch, cid),
  FOREIGN KEY (tenant_id, branch) REFERENCES branches(tenant_id, name)
);

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
  valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_to TIMESTAMPTZ,
  transaction_time TIMESTAMPTZ NOT NULL DEFAULT now(),
  expired_at TIMESTAMPTZ,
  justification_id UUID,
  source_evidence_cids BYTEA[] NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate', 'active', 'superseded', 'contested', 'quarantined', 'retracted')),
  version INT NOT NULL DEFAULT 1,
  superseded_by UUID,
  trust_tier SMALLINT NOT NULL DEFAULT 1,
  sensitivity SMALLINT NOT NULL DEFAULT 0,
  access_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  embedding VECTOR(1024),
  lexeme TSVECTOR,
  last_accessed TIMESTAMPTZ,
  access_count INT NOT NULL DEFAULT 0,
  FOREIGN KEY (tenant_id, branch) REFERENCES branches(tenant_id, name),
  CHECK (valid_to IS NULL OR valid_to > valid_from)
);

CREATE INDEX IF NOT EXISTS assertions_embedding_hnsw ON assertions USING hnsw (embedding vector_cosine_ops);
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
  access_policy JSONB NOT NULL DEFAULT '{}'::jsonb
);

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
  valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_to TIMESTAMPTZ,
  source_evidence_cids BYTEA[] NOT NULL DEFAULT '{}',
  access_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
  FOREIGN KEY (tenant_id, branch) REFERENCES branches(tenant_id, name),
  CHECK (valid_to IS NULL OR valid_to > valid_from)
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
  valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_to TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'active'
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
  at TIMESTAMPTZ NOT NULL DEFAULT now()
);

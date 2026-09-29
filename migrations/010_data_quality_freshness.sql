-- Route-specific OpenRouter evidence, freshness, source health, benchmark
-- versioning, and review triage. Historical rows remain intact.

ALTER TABLE provider_offerings ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'ACTIVE'
  CHECK (lifecycle_status IN ('ACTIVE','UNCONFIRMED','DEPRECATED','REMOVED','UNKNOWN'));
ALTER TABLE provider_offerings ADD COLUMN last_seen_at TEXT;
ALTER TABLE provider_offerings ADD COLUMN last_verified_at TEXT;
UPDATE provider_offerings
SET last_seen_at=COALESCE(last_seen_at,fetched_at),
    last_verified_at=COALESCE(last_verified_at,fetched_at);

-- Deliberately no self-referential FK: catalog snapshots topologically order
-- tables and a providers -> providers edge would form a cycle. IDs are audited
-- by the normalization query and the original rows remain as aliases.
ALTER TABLE providers ADD COLUMN canonical_provider_id INTEGER;
ALTER TABLE providers ADD COLUMN normalization_note TEXT;
UPDATE providers SET canonical_provider_id=(SELECT id FROM providers WHERE name='DeepInfra'),
  normalization_note='Explicit display-name normalization: Deep Infra -> DeepInfra'
  WHERE name='Deep Infra';
UPDATE providers SET canonical_provider_id=(SELECT id FROM providers WHERE name='Novita AI'),
  normalization_note='Explicit display-name normalization: NovitaAI -> Novita AI'
  WHERE name='NovitaAI';
UPDATE providers SET canonical_provider_id=(SELECT id FROM providers WHERE name='Z.ai'),
  normalization_note='Explicit case normalization: Z.AI -> Z.ai'
  WHERE name='Z.AI';

CREATE TABLE openrouter_route_variants (
  id INTEGER PRIMARY KEY,
  offering_id INTEGER NOT NULL REFERENCES provider_offerings(id) ON DELETE CASCADE,
  upstream_provider TEXT NOT NULL,
  provider_tag TEXT NOT NULL,
  route_name TEXT,
  quantization TEXT,
  endpoint_status INTEGER,
  context_limit INTEGER,
  max_prompt_tokens INTEGER,
  max_output_tokens INTEGER,
  tool_support TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (tool_support IN ('YES','NO','UNKNOWN')),
  tool_choice_json TEXT,
  structured_output_support TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (structured_output_support IN ('YES','NO','UNKNOWN')),
  input_modalities_json TEXT,
  output_modalities_json TEXT,
  input_price NUMERIC,
  output_price NUMERIC,
  cache_read_price NUMERIC,
  cache_write_price NUMERIC,
  discount_percent NUMERIC,
  original_input_price NUMERIC,
  original_output_price NUMERIC,
  original_price_inferred INTEGER NOT NULL DEFAULT 0 CHECK (original_price_inferred IN (0,1)),
  is_free INTEGER NOT NULL DEFAULT 0 CHECK (is_free IN (0,1)),
  rate_limit_note TEXT,
  model_expires_at TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  last_verified_at TEXT NOT NULL,
  source_id INTEGER NOT NULL REFERENCES sources(id),
  source_url TEXT NOT NULL,
  raw_payload_hash TEXT NOT NULL,
  UNIQUE(offering_id,provider_tag)
);
CREATE INDEX idx_openrouter_variants_available
  ON openrouter_route_variants(endpoint_status,is_free,discount_percent);

ALTER TABLE offers ADD COLUMN route_variant_id INTEGER REFERENCES openrouter_route_variants(id);
ALTER TABLE offers ADD COLUMN current_input_price NUMERIC;
ALTER TABLE offers ADD COLUMN current_output_price NUMERIC;
ALTER TABLE offers ADD COLUMN original_input_price NUMERIC;
ALTER TABLE offers ADD COLUMN original_output_price NUMERIC;
ALTER TABLE offers ADD COLUMN discount_percent NUMERIC;
ALTER TABLE offers ADD COLUMN original_price_inferred INTEGER NOT NULL DEFAULT 0
  CHECK (original_price_inferred IN (0,1));

CREATE TABLE source_health (
  source TEXT PRIMARY KEY,
  source_url TEXT,
  last_attempt_at TEXT NOT NULL,
  last_success_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('OK','ERROR','SCHEMA_CHANGED','QUARANTINED','NEVER')),
  records_imported INTEGER NOT NULL DEFAULT 0,
  records_changed INTEGER NOT NULL DEFAULT 0,
  http_status INTEGER,
  response_note TEXT,
  error TEXT,
  schema_hash TEXT,
  schema_changed_at TEXT
);

ALTER TABLE review_queue ADD COLUMN resolved_at TEXT;
ALTER TABLE review_queue ADD COLUMN resolution_note TEXT;
ALTER TABLE review_queue ADD COLUMN triage_class TEXT;

ALTER TABLE benchmarks ADD COLUMN is_current INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0,1));
ALTER TABLE benchmarks ADD COLUMN published_at TEXT;
ALTER TABLE benchmarks ADD COLUMN last_verified_at TEXT;
ALTER TABLE benchmarks ADD COLUMN methodology_url TEXT;
ALTER TABLE benchmarks ADD COLUMN task_count INTEGER;
ALTER TABLE benchmarks ADD COLUMN current_note TEXT;

ALTER TABLE benchmark_results ADD COLUMN harness_version TEXT;
ALTER TABLE benchmark_results ADD COLUMN task_subset TEXT;
ALTER TABLE benchmark_results ADD COLUMN tool_policy TEXT;
ALTER TABLE benchmark_results ADD COLUMN network_policy TEXT;
ALTER TABLE benchmark_results ADD COLUMN step_budget INTEGER;
ALTER TABLE benchmark_results ADD COLUMN token_budget INTEGER;
ALTER TABLE benchmark_results ADD COLUMN time_budget_seconds INTEGER;
ALTER TABLE benchmark_results ADD COLUMN attempts_per_task INTEGER;
ALTER TABLE benchmark_results ADD COLUMN grader_version TEXT;
ALTER TABLE benchmark_results ADD COLUMN input_tokens INTEGER;
ALTER TABLE benchmark_results ADD COLUMN cached_input_tokens INTEGER;
ALTER TABLE benchmark_results ADD COLUMN cache_write_tokens INTEGER;
ALTER TABLE benchmark_results ADD COLUMN answer_tokens INTEGER;
ALTER TABLE benchmark_results ADD COLUMN reasoning_tokens INTEGER;
ALTER TABLE benchmark_results ADD COLUMN total_output_tokens INTEGER;
ALTER TABLE benchmark_results ADD COLUMN model_cost_usd NUMERIC;
ALTER TABLE benchmark_results ADD COLUMN infrastructure_cost_usd NUMERIC;
ALTER TABLE benchmark_results ADD COLUMN cost_per_task_usd NUMERIC;
ALTER TABLE benchmark_results ADD COLUMN wall_time_seconds NUMERIC;
ALTER TABLE benchmark_results ADD COLUMN pricing_snapshot_at TEXT;
ALTER TABLE benchmark_results ADD COLUMN telemetry_complete INTEGER NOT NULL DEFAULT 0
  CHECK (telemetry_complete IN (0,1));

-- Legacy low-confidence results remain historical and are excluded from current
-- rankings until a publisher-backed importer supplies complete configuration.
UPDATE benchmarks SET is_current=0;

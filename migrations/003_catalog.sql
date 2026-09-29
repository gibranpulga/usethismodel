-- The original foundation tables remain for backwards compatibility.  This migration
-- introduces the normalized catalogue used by the application.
CREATE TABLE sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL DEFAULT 'catalog',
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reliability TEXT NOT NULL DEFAULT 'MEDIUM' CHECK (reliability IN ('HIGH','MEDIUM','LOW','UNKNOWN'))
);

CREATE TABLE labs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    website_url TEXT,
    source_id INTEGER REFERENCES sources(id)
);

ALTER TABLE models ADD COLUMN lab_id INTEGER REFERENCES labs(id);
ALTER TABLE models ADD COLUMN canonical_slug TEXT;
ALTER TABLE models ADD COLUMN status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','DEPRECATED','UNKNOWN'));
CREATE UNIQUE INDEX idx_models_canonical_slug ON models(canonical_slug) WHERE canonical_slug IS NOT NULL;

CREATE TABLE model_aliases (
    id INTEGER PRIMARY KEY,
    model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    provider_id INTEGER REFERENCES providers(id) ON DELETE CASCADE,
    source_id INTEGER REFERENCES sources(id),
    UNIQUE(alias, provider_id)
);

CREATE TABLE provider_offerings (
    id INTEGER PRIMARY KEY,
    model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    api_model_id TEXT NOT NULL,
    context_limit INTEGER,
    max_output_tokens INTEGER,
    tool_support TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (tool_support IN ('YES','NO','UNKNOWN')),
    structured_output_support TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (structured_output_support IN ('YES','NO','UNKNOWN')),
    free_status TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (free_status IN ('PAID','FREE','PROMOTIONAL','UNKNOWN')),
    rate_limit_note TEXT,
    caveat TEXT,
    source_id INTEGER REFERENCES sources(id),
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider_id, api_model_id)
);

CREATE TABLE offering_capabilities (
    id INTEGER PRIMARY KEY,
    offering_id INTEGER NOT NULL REFERENCES provider_offerings(id) ON DELETE CASCADE,
    capability TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('YES','NO','UNKNOWN')),
    source_id INTEGER REFERENCES sources(id),
    note TEXT,
    UNIQUE(offering_id, capability)
);

CREATE TABLE pricing_records (
    id INTEGER PRIMARY KEY,
    offering_id INTEGER NOT NULL REFERENCES provider_offerings(id) ON DELETE CASCADE,
    price_type TEXT NOT NULL CHECK (price_type IN ('INPUT','OUTPUT','CACHE_READ','CACHE_WRITE','BATCH_INPUT','BATCH_OUTPUT')),
    amount NUMERIC NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    unit TEXT NOT NULL DEFAULT 'per_1m_tokens',
    context_threshold INTEGER,
    valid_from TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    valid_until TEXT,
    source_id INTEGER REFERENCES sources(id),
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE plans (
    id INTEGER PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    source_id INTEGER REFERENCES sources(id),
    UNIQUE(provider_id, name)
);

ALTER TABLE offers ADD COLUMN plan_id INTEGER REFERENCES plans(id);
ALTER TABLE offers ADD COLUMN source_id INTEGER REFERENCES sources(id);
ALTER TABLE offers ADD COLUMN status TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (status IN ('ACTIVE','EXPIRED','UNKNOWN'));

ALTER TABLE harnesses ADD COLUMN organization TEXT;
ALTER TABLE harnesses ADD COLUMN open_source TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (open_source IN ('YES','NO','UNKNOWN'));
ALTER TABLE harnesses ADD COLUMN license TEXT;
ALTER TABLE harnesses ADD COLUMN interfaces TEXT NOT NULL DEFAULT 'UNKNOWN';
ALTER TABLE harnesses ADD COLUMN supported_os TEXT NOT NULL DEFAULT 'UNKNOWN';
ALTER TABLE harnesses ADD COLUMN headless_support TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (headless_support IN ('YES','NO','UNKNOWN'));
ALTER TABLE harnesses ADD COLUMN ssh_remote_support TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (ssh_remote_support IN ('YES','NO','UNKNOWN'));
ALTER TABLE harnesses ADD COLUMN openrouter_support TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (openrouter_support IN ('YES','NO','UNKNOWN'));
ALTER TABLE harnesses ADD COLUMN custom_openai_compatible TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (custom_openai_compatible IN ('YES','NO','UNKNOWN'));
ALTER TABLE harnesses ADD COLUMN direct_providers TEXT;
ALTER TABLE harnesses ADD COLUMN local_model_support TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (local_model_support IN ('YES','NO','UNKNOWN'));
ALTER TABLE harnesses ADD COLUMN login_requirement TEXT NOT NULL DEFAULT 'UNKNOWN';
ALTER TABLE harnesses ADD COLUMN skills_plugins TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (skills_plugins IN ('YES','NO','UNKNOWN'));
ALTER TABLE harnesses ADD COLUMN subagents TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (subagents IN ('YES','NO','UNKNOWN'));
ALTER TABLE harnesses ADD COLUMN browser_support TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (browser_support IN ('YES','NO','UNKNOWN'));
ALTER TABLE harnesses ADD COLUMN computer_use_support TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (computer_use_support IN ('YES','NO','UNKNOWN'));
ALTER TABLE harnesses ADD COLUMN source_id INTEGER REFERENCES sources(id);

CREATE TABLE harness_provider_compatibility (
    id INTEGER PRIMARY KEY,
    harness_id INTEGER NOT NULL REFERENCES harnesses(id) ON DELETE CASCADE,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    support_mode TEXT NOT NULL CHECK (support_mode IN ('NATIVE','OPENAI_COMPATIBLE','OPENROUTER','CONFIGURATION','NO','UNKNOWN')),
    source_id INTEGER REFERENCES sources(id),
    note TEXT,
    UNIQUE(harness_id, provider_id)
);

CREATE TABLE harness_mcp_capabilities (
    id INTEGER PRIMARY KEY,
    harness_id INTEGER NOT NULL REFERENCES harnesses(id) ON DELETE CASCADE,
    transport TEXT NOT NULL CHECK (transport IN ('STDIO','STREAMABLE_HTTP','SSE','OAUTH','TOOLS','RESOURCES','PROMPTS')),
    state TEXT NOT NULL CHECK (state IN ('YES','NO','UNKNOWN')),
    source_id INTEGER REFERENCES sources(id),
    note TEXT,
    UNIQUE(harness_id, transport)
);

CREATE TABLE harness_model_overrides (
    id INTEGER PRIMARY KEY,
    harness_id INTEGER NOT NULL REFERENCES harnesses(id) ON DELETE CASCADE,
    model_id INTEGER REFERENCES models(id) ON DELETE CASCADE,
    offering_id INTEGER REFERENCES provider_offerings(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('COMPATIBLE','COMPATIBLE_WITH_CONFIGURATION','PARTIAL','NOT_COMPATIBLE','UNKNOWN')),
    reason TEXT NOT NULL,
    source_id INTEGER REFERENCES sources(id),
    CHECK (model_id IS NOT NULL OR offering_id IS NOT NULL)
);

CREATE TABLE model_use_case_scores (
    id INTEGER PRIMARY KEY,
    model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    use_case_id INTEGER NOT NULL REFERENCES use_cases(id) ON DELETE CASCADE,
    classification TEXT NOT NULL CHECK (classification IN ('RECOMMENDED','SUPPORTED','UNKNOWN','NOT_RECOMMENDED')),
    score REAL,
    confidence TEXT NOT NULL CHECK (confidence IN ('HIGH','MEDIUM','LOW','UNKNOWN')),
    rationale TEXT,
    source_id INTEGER REFERENCES sources(id),
    UNIQUE(model_id, use_case_id, source_id)
);

CREATE TABLE benchmarks (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    source_id INTEGER REFERENCES sources(id),
    UNIQUE(name, version)
);

CREATE TABLE benchmark_results (
    id INTEGER PRIMARY KEY,
    benchmark_id INTEGER NOT NULL REFERENCES benchmarks(id) ON DELETE CASCADE,
    model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    offering_id INTEGER REFERENCES provider_offerings(id) ON DELETE SET NULL,
    model_version TEXT,
    score REAL NOT NULL,
    metric TEXT NOT NULL,
    harness_name TEXT,
    scaffold TEXT,
    reasoning_setting TEXT,
    confidence_interval TEXT,
    evaluated_at TEXT,
    source_id INTEGER REFERENCES sources(id),
    confidence TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (confidence IN ('HIGH','MEDIUM','LOW','UNKNOWN'))
);

CREATE TABLE data_change_log (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    change_type TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    source_id INTEGER REFERENCES sources(id),
    changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_offerings_model ON provider_offerings(model_id);
CREATE INDEX idx_offerings_provider ON provider_offerings(provider_id);
CREATE INDEX idx_pricing_offering ON pricing_records(offering_id);
CREATE INDEX idx_aliases_alias ON model_aliases(alias);
CREATE INDEX idx_benchmark_results_model ON benchmark_results(model_id);

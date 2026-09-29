ALTER TABLE models ADD COLUMN first_seen_at TEXT;
UPDATE models SET first_seen_at=created_at;
ALTER TABLE models ADD COLUMN release_date_kind TEXT NOT NULL DEFAULT 'unverified';
ALTER TABLE provider_offerings ADD COLUMN first_seen_at TEXT;
UPDATE provider_offerings SET first_seen_at=fetched_at;
CREATE TABLE data_observations (
 id INTEGER PRIMARY KEY, entity TEXT NOT NULL, field TEXT NOT NULL,
 source TEXT NOT NULL, source_url TEXT NOT NULL, source_id INTEGER REFERENCES sources(id),
 value_json TEXT NOT NULL, priority INTEGER NOT NULL, observed_at TEXT NOT NULL,
 accepted INTEGER NOT NULL DEFAULT 1, evidence TEXT NOT NULL,
 UNIQUE(entity,field,source,value_json,observed_at)
);
CREATE INDEX idx_observations_entity ON data_observations(entity,field,source,id);
CREATE TABLE selected_facts (
 entity TEXT NOT NULL, field TEXT NOT NULL, observation_id INTEGER NOT NULL REFERENCES data_observations(id),
 PRIMARY KEY(entity,field)
);
CREATE TABLE review_queue (
 id TEXT PRIMARY KEY, entity TEXT NOT NULL, proposed_change TEXT NOT NULL,
 current_value TEXT, proposed_value TEXT, sources TEXT NOT NULL, evidence TEXT NOT NULL,
 confidence TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
 created_at TEXT NOT NULL
);
CREATE TABLE source_state (source TEXT PRIMARY KEY, manifest_json TEXT NOT NULL);
CREATE TABLE data_runs (id TEXT PRIMARY KEY, completed_at TEXT NOT NULL, summary_json TEXT NOT NULL);
CREATE TABLE applied_snapshots (digest TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);

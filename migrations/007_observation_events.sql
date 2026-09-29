-- A value can recur within one fetch (legacy baseline, then fresh evidence).
-- Event IDs establish order; timestamps must not accidentally deduplicate it.
PRAGMA foreign_keys=OFF;
BEGIN;
CREATE TABLE data_observations_new (
 id INTEGER PRIMARY KEY, entity TEXT NOT NULL, field TEXT NOT NULL,
 source TEXT NOT NULL, source_url TEXT NOT NULL, source_id INTEGER REFERENCES sources(id),
 value_json TEXT NOT NULL, priority INTEGER NOT NULL, observed_at TEXT NOT NULL,
 accepted INTEGER NOT NULL DEFAULT 1, evidence TEXT NOT NULL
);
INSERT INTO data_observations_new SELECT * FROM data_observations;
DROP TABLE data_observations;
ALTER TABLE data_observations_new RENAME TO data_observations;
CREATE INDEX idx_observations_entity ON data_observations(entity,field,source,id);
COMMIT;
PRAGMA foreign_keys=ON;

-- Canonical identity is established separately from the provider's callable ID.
-- Mappings are exact, auditable assertions; no fuzzy matching is implied.
CREATE TABLE model_identity_mappings (
  id INTEGER PRIMARY KEY,
  provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
  provider_model_id TEXT NOT NULL,
  model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
  evidence_source_id INTEGER REFERENCES sources(id),
  evidence_url TEXT NOT NULL DEFAULT '',
  evidence TEXT NOT NULL,
  confidence TEXT NOT NULL CHECK(confidence IN ('HIGH','MEDIUM')),
  status TEXT NOT NULL DEFAULT 'ACCEPTED' CHECK(status IN ('ACCEPTED','REJECTED','PENDING')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(provider_id, provider_model_id)
);
CREATE TABLE model_identity_review (
  id INTEGER PRIMARY KEY,
  provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
  provider_model_id TEXT NOT NULL,
  candidate_model_id INTEGER REFERENCES models(id) ON DELETE SET NULL,
  observation_id INTEGER REFERENCES data_observations(id) ON DELETE SET NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','RESOLVED','DISMISSED')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(provider_id, provider_model_id, status)
);
CREATE INDEX idx_identity_mapping_model ON model_identity_mappings(model_id);

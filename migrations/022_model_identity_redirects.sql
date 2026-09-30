CREATE TABLE model_identity_redirects (
  old_model_id INTEGER PRIMARY KEY,
  old_slug TEXT NOT NULL UNIQUE,
  old_name TEXT NOT NULL,
  target_model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
  evidence_source_id INTEGER REFERENCES sources(id),
  evidence_url TEXT NOT NULL,
  evidence TEXT NOT NULL,
  verified_at TEXT NOT NULL
);

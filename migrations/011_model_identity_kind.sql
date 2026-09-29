-- Moving aliases such as "latest" are callable model IDs but not immutable
-- releases. Preserve them without presenting them as versioned checkpoints.
ALTER TABLE models ADD COLUMN identity_kind TEXT NOT NULL DEFAULT 'RELEASE'
  CHECK (identity_kind IN ('RELEASE','MOVING_ALIAS','ROUTER','UNKNOWN'));
UPDATE models SET identity_kind='MOVING_ALIAS'
WHERE lower(COALESCE(canonical_slug,'')) LIKE '%latest%'
   OR lower(COALESCE(canonical_name,'')) LIKE '%latest%';
UPDATE models SET identity_kind='ROUTER' WHERE canonical_slug='openrouter/free';

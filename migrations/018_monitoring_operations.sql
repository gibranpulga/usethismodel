ALTER TABLE plans ADD COLUMN first_seen_at TEXT;
ALTER TABLE plans ADD COLUMN last_checked_at TEXT;
ALTER TABLE plans ADD COLUMN last_changed_at TEXT;
ALTER TABLE plans ADD COLUMN last_verified_at TEXT;

UPDATE plans SET first_seen_at=COALESCE(first_seen_at,verified_at),
                  last_verified_at=COALESCE(last_verified_at,verified_at);

CREATE TABLE plan_value_history (
  id INTEGER PRIMARY KEY,
  plan_id INTEGER NOT NULL,
  captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  source_id INTEGER,
  verified_at TEXT,
  name TEXT NOT NULL,
  description TEXT,
  plan_type TEXT NOT NULL,
  monthly_price NUMERIC,
  annual_price NUMERIC,
  currency TEXT NOT NULL,
  price_note TEXT,
  models_included TEXT,
  api_access TEXT NOT NULL,
  coding_agent_access TEXT NOT NULL,
  quota_description TEXT,
  reset_interval TEXT,
  published_limit TEXT,
  fair_use TEXT,
  region_restrictions TEXT,
  is_coding INTEGER NOT NULL,
  status TEXT NOT NULL
);
CREATE INDEX idx_plan_value_history ON plan_value_history(plan_id,captured_at DESC);
CREATE TRIGGER archive_plan_values_before_update
BEFORE UPDATE OF name,description,source_id,plan_type,monthly_price,annual_price,currency,
  price_note,models_included,api_access,coding_agent_access,quota_description,reset_interval,
  published_limit,fair_use,region_restrictions,is_coding,status,verified_at ON plans
WHEN OLD.name IS NOT NEW.name OR OLD.description IS NOT NEW.description OR OLD.source_id IS NOT NEW.source_id
  OR OLD.plan_type IS NOT NEW.plan_type OR OLD.monthly_price IS NOT NEW.monthly_price
  OR OLD.annual_price IS NOT NEW.annual_price OR OLD.currency IS NOT NEW.currency
  OR OLD.price_note IS NOT NEW.price_note OR OLD.models_included IS NOT NEW.models_included
  OR OLD.api_access IS NOT NEW.api_access OR OLD.coding_agent_access IS NOT NEW.coding_agent_access
  OR OLD.quota_description IS NOT NEW.quota_description OR OLD.reset_interval IS NOT NEW.reset_interval
  OR OLD.published_limit IS NOT NEW.published_limit OR OLD.fair_use IS NOT NEW.fair_use
  OR OLD.region_restrictions IS NOT NEW.region_restrictions OR OLD.is_coding IS NOT NEW.is_coding
  OR OLD.status IS NOT NEW.status OR OLD.verified_at IS NOT NEW.verified_at
BEGIN
  INSERT INTO plan_value_history(plan_id,captured_at,source_id,verified_at,name,description,plan_type,
    monthly_price,annual_price,currency,price_note,models_included,api_access,coding_agent_access,
    quota_description,reset_interval,published_limit,fair_use,region_restrictions,is_coding,status)
  VALUES(OLD.id,datetime('now'),OLD.source_id,OLD.verified_at,OLD.name,OLD.description,OLD.plan_type,
    OLD.monthly_price,OLD.annual_price,OLD.currency,OLD.price_note,OLD.models_included,OLD.api_access,
    OLD.coding_agent_access,OLD.quota_description,OLD.reset_interval,OLD.published_limit,OLD.fair_use,
    OLD.region_restrictions,OLD.is_coding,OLD.status);
END;

CREATE TABLE documentation_monitor_state (
  source_id INTEGER PRIMARY KEY REFERENCES sources(id),
  first_seen_at TEXT NOT NULL,
  last_checked_at TEXT NOT NULL,
  last_changed_at TEXT,
  last_verified_at TEXT,
  content_hash TEXT,
  schema_hash TEXT,
  status TEXT NOT NULL CHECK(status IN ('OK','ERROR','CHANGED','SCHEMA_CHANGED')),
  error_kind TEXT,
  http_status INTEGER
);
CREATE INDEX idx_doc_monitor_status ON documentation_monitor_state(status,last_checked_at);

CREATE TABLE rate_limit_windows (
  client_hash TEXT NOT NULL,
  window_start INTEGER NOT NULL,
  request_count INTEGER NOT NULL,
  PRIMARY KEY(client_hash,window_start)
);

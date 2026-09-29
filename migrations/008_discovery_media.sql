-- Discovery, route-level offers, media-native pricing and model metadata.
-- Keep the existing route-first catalogue; extend it without introducing a
-- second product/data architecture.

ALTER TABLE offers ADD COLUMN offering_id INTEGER REFERENCES provider_offerings(id);
ALTER TABLE offers ADD COLUMN description TEXT;
ALTER TABLE offers ADD COLUMN first_seen_at TEXT;
ALTER TABLE offers ADD COLUMN last_verified_at TEXT;
ALTER TABLE offers ADD COLUMN verification_note TEXT;
ALTER TABLE offers ADD COLUMN privacy_caveat TEXT;

ALTER TABLE provider_offerings ADD COLUMN privacy_caveat TEXT;
ALTER TABLE provider_offerings ADD COLUMN commercial_use TEXT NOT NULL DEFAULT 'UNKNOWN'
  CHECK (commercial_use IN ('YES','NO','CONDITIONAL','UNKNOWN'));

CREATE TABLE model_media_features (
  model_id INTEGER PRIMARY KEY REFERENCES models(id) ON DELETE CASCADE,
  text_to_3d TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (text_to_3d IN ('YES','NO','UNKNOWN')),
  image_to_3d TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (image_to_3d IN ('YES','NO','UNKNOWN')),
  multi_view TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (multi_view IN ('YES','NO','UNKNOWN')),
  texturing TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (texturing IN ('YES','NO','UNKNOWN')),
  rigging TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (rigging IN ('YES','NO','UNKNOWN')),
  topology_low_poly TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (topology_low_poly IN ('YES','NO','UNKNOWN')),
  output_formats TEXT,
  generation_time_note TEXT,
  commercial_use_note TEXT,
  evidence_kind TEXT NOT NULL DEFAULT 'VENDOR_CLAIM'
    CHECK (evidence_kind IN ('VERIFIED','VENDOR_CLAIM','INDEPENDENT_BENCHMARK','UNKNOWN')),
  source_id INTEGER REFERENCES sources(id),
  last_verified_at TEXT
);

-- SQLite cannot alter a CHECK constraint in place. Rebuild the pricing table
-- so history continues to use one table while supporting media-native units.
ALTER TABLE pricing_records RENAME TO pricing_records_legacy;
CREATE TABLE pricing_records (
    id INTEGER PRIMARY KEY,
    offering_id INTEGER NOT NULL REFERENCES provider_offerings(id) ON DELETE CASCADE,
    price_type TEXT NOT NULL CHECK (price_type IN (
      'INPUT','OUTPUT','CACHE_READ','CACHE_WRITE','BATCH_INPUT','BATCH_OUTPUT',
      'IMAGE','MEGAPIXEL','SECOND','VIDEO','AUDIO_MINUTE','GENERATION','THREE_D_GENERATION'
    )),
    amount NUMERIC NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    unit TEXT NOT NULL DEFAULT 'per_1m_tokens',
    context_threshold INTEGER,
    valid_from TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    valid_until TEXT,
    source_id INTEGER REFERENCES sources(id),
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    price_note TEXT,
    promotional INTEGER NOT NULL DEFAULT 0 CHECK (promotional IN (0,1))
);
INSERT INTO pricing_records
  (id,offering_id,price_type,amount,currency,unit,context_threshold,valid_from,valid_until,source_id,fetched_at)
SELECT id,offering_id,price_type,amount,currency,unit,context_threshold,valid_from,valid_until,source_id,fetched_at
FROM pricing_records_legacy;
DROP TABLE pricing_records_legacy;
CREATE INDEX idx_pricing_offering ON pricing_records(offering_id);
CREATE INDEX idx_pricing_history ON pricing_records(offering_id,price_type,valid_from,id);
CREATE INDEX idx_offers_status ON offers(status,ends_at);

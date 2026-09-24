CREATE TABLE models (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    vendor TEXT NOT NULL,
    modality TEXT NOT NULL DEFAULT 'text',
    open_weights INTEGER NOT NULL DEFAULT 0 CHECK (open_weights IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE providers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    website_url TEXT
);
CREATE TABLE routes (
    id INTEGER PRIMARY KEY,
    model_id INTEGER NOT NULL REFERENCES models(id),
    provider_id INTEGER NOT NULL REFERENCES providers(id),
    input_price_per_million REAL,
    output_price_per_million REAL,
    supports_tools INTEGER CHECK (supports_tools IN (0, 1)),
    source_url TEXT,
    checked_at TEXT,
    UNIQUE(model_id, provider_id)
);
CREATE TABLE harnesses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    supports_mcp INTEGER CHECK (supports_mcp IN (0, 1)),
    website_url TEXT
);
CREATE TABLE offers (
    id INTEGER PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id),
    title TEXT NOT NULL,
    offer_type TEXT NOT NULL,
    terms_url TEXT,
    starts_at TEXT,
    ends_at TEXT
);

CREATE TABLE use_cases (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE route_capabilities (
    id INTEGER PRIMARY KEY,
    route_id INTEGER NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    capability TEXT NOT NULL,
    supported INTEGER NOT NULL CHECK (supported IN (0, 1)),
    caveat TEXT,
    source_url TEXT,
    checked_at TEXT,
    UNIQUE(route_id, capability)
);

CREATE TABLE compatibility_notes (
    id INTEGER PRIMARY KEY,
    harness_id INTEGER NOT NULL REFERENCES harnesses(id) ON DELETE CASCADE,
    route_id INTEGER NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('supported', 'partial', 'unknown', 'unsupported')),
    note TEXT,
    source_url TEXT,
    checked_at TEXT,
    UNIQUE(harness_id, route_id)
);

CREATE TABLE benchmark_measurements (
    id INTEGER PRIMARY KEY,
    model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    benchmark_name TEXT NOT NULL,
    benchmark_version TEXT,
    task TEXT,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    evaluated_at TEXT,
    source_url TEXT NOT NULL,
    license_note TEXT
);

CREATE INDEX idx_routes_model_id ON routes(model_id);
CREATE INDEX idx_routes_provider_id ON routes(provider_id);
CREATE INDEX idx_compatibility_route_id ON compatibility_notes(route_id);
CREATE INDEX idx_benchmarks_model_id ON benchmark_measurements(model_id);

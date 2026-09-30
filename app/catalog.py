"""Repeatable, non-destructive catalogue synchronization from public JSON sources."""

import json
from urllib.request import Request, urlopen

MODELS_DEV = "https://models.dev/api.json"
OPENROUTER = "https://openrouter.ai/api/v1/models"


def _fetch(url):
    request = Request(url, headers={"User-Agent": "UseThisModel catalog sync/0.2"})
    with urlopen(request, timeout=45) as response:  # no credentials are sent
        return json.load(response)


def _source(db, name, url):
    db.execute(
        "INSERT OR IGNORE INTO sources(name,url,source_type,reliability) VALUES(?,?,?,?)",
        (name, url, "machine-readable catalog", "MEDIUM"),
    )
    return db.execute("SELECT id FROM sources WHERE url=?", (url,)).fetchone()[0]


def _provider(db, name, website=None):
    db.execute("INSERT OR IGNORE INTO providers(name,website_url) VALUES(?,?)", (name, website))
    return db.execute("SELECT id FROM providers WHERE name=?", (name,)).fetchone()[0]


def _model(db, slug, name, open_weights, modality):
    """Create a model shell without inferring authorship from a route provider.

    Provider/aggregator display names describe where a route is served, not who
    created the underlying model. Author identity must come from explicit,
    source-backed metadata; the current adapters do not provide that field.
    """
    existing = db.execute("SELECT id FROM models WHERE canonical_slug=?", (slug,)).fetchone()
    if existing:
        return existing[0]
    db.execute(
        """INSERT OR IGNORE INTO models(canonical_name,vendor,modality,open_weights,lab_id,canonical_slug)
           VALUES(?,?,?,?,?,?)""",
        (name, "Unknown", modality, int(bool(open_weights)), None, slug),
    )
    row = db.execute("SELECT id FROM models WHERE canonical_slug=?", (slug,)).fetchone()
    if not row:  # names in third-party catalogues can collide across distinct releases
        db.execute(
            "INSERT INTO models(canonical_name,vendor,modality,open_weights,lab_id,canonical_slug) VALUES(?,?,?,?,?,?)",
            (f"{name} ({slug})", "Unknown", modality, int(bool(open_weights)), None, slug),
        )
        row = db.execute("SELECT id FROM models WHERE canonical_slug=?", (slug,)).fetchone()
    return row[0]


def sync_models_dev(db, payload=None):
    """Compatibility entry point; all writes pass the safe deterministic pipeline."""
    from .data_update import update
    from .update_sources import parse_models_dev
    records = parse_models_dev(payload if payload is not None else _fetch(MODELS_DEV))
    return update(db, records, [], {})


def sync_openrouter(db, payload=None):
    from .data_update import update
    from .update_sources import parse_openrouter
    records = parse_openrouter(payload if payload is not None else _fetch(OPENROUTER))
    return update(db, records, [], {})


def sync(db, models_dev_payload=None, openrouter_payload=None):
    from .data_update import update
    from .update_sources import fetch_sources, parse_models_dev, parse_openrouter
    if models_dev_payload is None and openrouter_payload is None:
        records, failures, manifests = fetch_sources()
    else:
        records = parse_models_dev(models_dev_payload or {}) + parse_openrouter(openrouter_payload or {"data": []})
        failures, manifests = [], {}
    with db:
        return update(db, records, failures, manifests)


if __name__ == "__main__":
    from .data_update import main
    main()

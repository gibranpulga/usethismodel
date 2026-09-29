"""Repeatable, non-destructive catalogue synchronization from public JSON sources."""

import json
from datetime import datetime, timezone
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


def _model(db, slug, name, provider_name, open_weights, modality, source_id):
    lab_name = provider_name.split("/")[0].replace("-ai", "").title()
    db.execute("INSERT OR IGNORE INTO labs(name,source_id) VALUES(?,?)", (lab_name, source_id))
    lab_id = db.execute("SELECT id FROM labs WHERE name=?", (lab_name,)).fetchone()[0]
    existing = db.execute("SELECT id FROM models WHERE canonical_slug=?", (slug,)).fetchone()
    if existing:
        return existing[0]
    db.execute(
        """INSERT OR IGNORE INTO models(canonical_name,vendor,modality,open_weights,lab_id,canonical_slug)
           VALUES(?,?,?,?,?,?)""",
        (name, lab_name, modality, int(bool(open_weights)), lab_id, slug),
    )
    row = db.execute("SELECT id FROM models WHERE canonical_slug=?", (slug,)).fetchone()
    if not row:  # names in third-party catalogues can collide across distinct releases
        db.execute(
            "INSERT INTO models(canonical_name,vendor,modality,open_weights,lab_id,canonical_slug) VALUES(?,?,?,?,?,?)",
            (f"{name} ({slug})", lab_name, modality, int(bool(open_weights)), lab_id, slug),
        )
        row = db.execute("SELECT id FROM models WHERE canonical_slug=?", (slug,)).fetchone()
    return row[0]


def _price_rows(db, offering_id, cost, source_id, now):
    mapping = {
        "input": "INPUT",
        "output": "OUTPUT",
        "cache_read": "CACHE_READ",
        "cache_write": "CACHE_WRITE",
    }
    for key, price_type in mapping.items():
        if key in cost and cost[key] is not None:
            exists = db.execute(
                "SELECT 1 FROM pricing_records WHERE offering_id=? AND price_type=? AND amount=? AND valid_until IS NULL",
                (offering_id, price_type, cost[key]),
            ).fetchone()
            if not exists:
                db.execute(
                    "UPDATE pricing_records SET valid_until=? WHERE offering_id=? AND price_type=? AND valid_until IS NULL",
                    (now, offering_id, price_type),
                )
                db.execute(
                    "INSERT INTO pricing_records(offering_id,price_type,amount,source_id,valid_from,fetched_at) VALUES(?,?,?,?,?,?)",
                    (offering_id, price_type, cost[key], source_id, now, now),
                )


def sync_models_dev(db, payload=None):
    payload = payload or _fetch(MODELS_DEV)
    source_id = _source(db, "Models.dev catalog", MODELS_DEV)
    now = datetime.now(timezone.utc).isoformat()
    counts = {"models": 0, "offerings": 0}
    for provider_key, provider in payload.items():
        provider_id = _provider(db, provider.get("name", provider_key), provider.get("doc"))
        for api_id, item in provider.get("models", {}).items():
            canonical = item.get("canonical_model_id") or api_id.lower()
            model_id = _model(
                db,
                canonical,
                item.get("name", api_id),
                canonical,
                item.get("open_weights", False),
                ",".join(item.get("modalities", {}).get("input", ["text"])),
                source_id,
            )
            db.execute(
                "INSERT OR IGNORE INTO model_aliases(model_id,alias,provider_id,source_id) VALUES(?,?,?,?)",
                (model_id, api_id, provider_id, source_id),
            )
            before = db.total_changes
            db.execute(
                """INSERT INTO provider_offerings(model_id,provider_id,api_model_id,context_limit,max_output_tokens,tool_support,structured_output_support,source_id,fetched_at)
                   VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(provider_id,api_model_id) DO UPDATE SET context_limit=excluded.context_limit,max_output_tokens=excluded.max_output_tokens,tool_support=excluded.tool_support,structured_output_support=excluded.structured_output_support,source_id=excluded.source_id,fetched_at=excluded.fetched_at""",
                (
                    model_id,
                    provider_id,
                    api_id,
                    item.get("limit", {}).get("context"),
                    item.get("limit", {}).get("output"),
                    "YES"
                    if item.get("tool_call") is True
                    else "NO"
                    if item.get("tool_call") is False
                    else "UNKNOWN",
                    "YES"
                    if item.get("structured_output") is True
                    else "NO"
                    if item.get("structured_output") is False
                    else "UNKNOWN",
                    source_id,
                    now,
                ),
            )
            offering_id = db.execute(
                "SELECT id FROM provider_offerings WHERE provider_id=? AND api_model_id=?",
                (provider_id, api_id),
            ).fetchone()[0]
            _price_rows(db, offering_id, item.get("cost") or {}, source_id, now)
            counts["models"] += int(before != db.total_changes)
            counts["offerings"] += 1
    return counts


def sync_openrouter(db, payload=None):
    payload = payload or _fetch(OPENROUTER)
    source_id = _source(db, "OpenRouter model API", OPENROUTER)
    provider_id = _provider(db, "OpenRouter", "https://openrouter.ai/")
    now = datetime.now(timezone.utc).isoformat()
    count = 0
    for item in payload.get("data", []):
        slug = item.get("canonical_slug") or item["id"]
        model_id = _model(
            db,
            slug,
            item.get("name", item["id"]),
            slug,
            False,
            item.get("architecture", {}).get("modality", "text"),
            source_id,
        )
        db.execute(
            "INSERT OR IGNORE INTO model_aliases(model_id,alias,provider_id,source_id) VALUES(?,?,?,?)",
            (model_id, item["id"], provider_id, source_id),
        )
        tools = "YES" if "tools" in item.get("supported_parameters", []) else "UNKNOWN"
        db.execute(
            """INSERT INTO provider_offerings(model_id,provider_id,api_model_id,context_limit,max_output_tokens,tool_support,source_id,fetched_at)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(provider_id,api_model_id) DO UPDATE SET context_limit=excluded.context_limit,max_output_tokens=excluded.max_output_tokens,tool_support=excluded.tool_support,source_id=excluded.source_id,fetched_at=excluded.fetched_at""",
            (
                model_id,
                provider_id,
                item["id"],
                item.get("context_length"),
                item.get("top_provider", {}).get("max_completion_tokens"),
                tools,
                source_id,
                now,
            ),
        )
        offering_id = db.execute(
            "SELECT id FROM provider_offerings WHERE provider_id=? AND api_model_id=?",
            (provider_id, item["id"]),
        ).fetchone()[0]
        price = item.get("pricing", {})
        _price_rows(
            db,
            offering_id,
            {
                "input": float(price["prompt"]) * 1000000 if price.get("prompt") else None,
                "output": float(price["completion"]) * 1000000 if price.get("completion") else None,
                "cache_read": float(price["input_cache_read"]) * 1000000
                if price.get("input_cache_read")
                else None,
            },
            source_id,
            now,
        )
        count += 1
    return {"offerings": count}


def sync(db, models_dev_payload=None, openrouter_payload=None):
    result = sync_models_dev(db, models_dev_payload)
    result.update(
        {f"openrouter_{k}": v for k, v in sync_openrouter(db, openrouter_payload).items()}
    )
    db.commit()
    return result


if __name__ == "__main__":
    import os

    from . import create_app
    from .db import get_db

    app = create_app({"DATABASE": os.environ.get("DATABASE_PATH", "/data/usethismodel.sqlite3")})
    with app.app_context():
        print(sync(get_db()))

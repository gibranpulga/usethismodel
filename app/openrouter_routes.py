"""OpenRouter provider-endpoint discovery.

The ordinary model catalog is an aggregate route. Promotions and exact free
capacity live on provider endpoints and must never be generalized to the model.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
from urllib.request import Request, urlopen

from .catalog import _source

MODELS_URL = "https://openrouter.ai/api/v1/models"
ENDPOINT_URL = "https://openrouter.ai/api/v1/models/{model_id}/endpoints"
ENDPOINT_DOCS = "https://openrouter.ai/docs/api/api-reference/endpoints/list-endpoints"
FREE_RATE_LIMIT = "Free account: 20 RPM and 50 requests/day; 1,000/day after purchasing at least $10 credits."


def _fetch(url):
    request = Request(
        url,
        headers={
            "User-Agent": "UseThisModel route freshness monitor/1.0",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=45) as response:
        return json.load(response)


def _decimal(value):
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid OpenRouter endpoint price") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("Invalid OpenRouter endpoint price")
    return result * Decimal(1_000_000)


def _state(parameters, name):
    if not isinstance(parameters, list):
        return "UNKNOWN"
    return "YES" if name in parameters else "NO"


def parse_endpoint_payload(payload, source_url):
    """Return normalized route variants from one documented endpoint payload."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise ValueError("Invalid OpenRouter endpoint response")
    model = payload["data"]
    model_id = model.get("id")
    endpoints = model.get("endpoints")
    if not isinstance(model_id, str) or not model_id or not isinstance(endpoints, list):
        raise ValueError("Invalid OpenRouter endpoint model")
    architecture = model.get("architecture") if isinstance(model.get("architecture"), dict) else {}
    result = []
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            raise ValueError("Invalid OpenRouter endpoint row")
        tag = endpoint.get("tag")
        provider = endpoint.get("provider_name")
        if not isinstance(tag, str) or not tag or not isinstance(provider, str) or not provider:
            raise ValueError("OpenRouter endpoint lacks provider identity")
        pricing = endpoint.get("pricing") if isinstance(endpoint.get("pricing"), dict) else {}
        input_price = _decimal(pricing.get("prompt"))
        output_price = _decimal(pricing.get("completion"))
        discount = pricing.get("discount")
        try:
            discount = Decimal(str(discount)) if discount is not None else Decimal(0)
        except InvalidOperation as exc:
            raise ValueError("Invalid OpenRouter discount") from exc
        # Negative values are explicit route markups, not promotions. Preserve
        # them for price transparency without creating an offer.
        if not discount.is_finite() or discount < -1 or discount > 1:
            raise ValueError("Invalid OpenRouter discount")
        original_input = input_price / (1 - discount) if input_price is not None and 0 < discount < 1 else None
        original_output = output_price / (1 - discount) if output_price is not None and 0 < discount < 1 else None
        params = endpoint.get("supported_parameters")
        normalized = {
                "model_id": model_id,
                "model_name": model.get("name") or model_id,
                "upstream_provider": provider,
                "provider_tag": tag,
                "route_name": endpoint.get("name"),
                "quantization": endpoint.get("quantization"),
                "endpoint_status": endpoint.get("status"),
                "context_limit": endpoint.get("context_length"),
                "max_prompt_tokens": endpoint.get("max_prompt_tokens"),
                "max_output_tokens": endpoint.get("max_completion_tokens"),
                "tool_support": _state(params, "tools"),
                "tool_choice_json": json.dumps(endpoint.get("supports_tool_choice"), sort_keys=True) if isinstance(endpoint.get("supports_tool_choice"), dict) else None,
                "structured_output_support": _state(params, "structured_outputs"),
                "input_modalities_json": json.dumps(architecture.get("input_modalities")) if isinstance(architecture.get("input_modalities"), list) else None,
                "output_modalities_json": json.dumps(architecture.get("output_modalities")) if isinstance(architecture.get("output_modalities"), list) else None,
                "input_price": float(input_price) if input_price is not None else None,
                "output_price": float(output_price) if output_price is not None else None,
                "cache_read_price": float(_decimal(pricing.get("input_cache_read"))) if pricing.get("input_cache_read") is not None else None,
                "cache_write_price": float(_decimal(pricing.get("input_cache_write"))) if pricing.get("input_cache_write") is not None else None,
                "discount_percent": float(discount * 100),
                "original_input_price": float(original_input) if original_input is not None else None,
                "original_output_price": float(original_output) if original_output is not None else None,
                "original_price_inferred": int(original_input is not None or original_output is not None),
                "is_free": int(input_price == 0 and output_price == 0 and input_price is not None and output_price is not None),
                "rate_limit_note": FREE_RATE_LIMIT if input_price == 0 and output_price == 0 else None,
                "model_expires_at": model.get("expiration_date"),
                "source_url": source_url,
        }
        # Hash only persisted factual fields. Volatile uptime/latency telemetry
        # must not make an unchanged price or capability look changed.
        normalized["raw_payload_hash"] = hashlib.sha256(
            json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        result.append(normalized)
    return result


def fetch_openrouter_variants(fetcher=None, model_payload=None, workers=12):
    """Fetch all exact endpoints; a failed model is retained as a source failure."""
    fetcher = fetcher or _fetch
    catalog = model_payload if model_payload is not None else fetcher(MODELS_URL)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("data"), list):
        raise ValueError("Invalid OpenRouter model catalog")
    ids = [item.get("id") for item in catalog["data"] if isinstance(item, dict)]
    if not ids or any(not isinstance(model_id, str) or "/" not in model_id for model_id in ids):
        raise ValueError("Invalid OpenRouter model IDs")
    variants, failures = [], []

    def load(model_id):
        url = ENDPOINT_URL.format(model_id=quote(model_id, safe="/:"))
        return model_id, parse_endpoint_payload(fetcher(url), url)

    with ThreadPoolExecutor(max_workers=max(1, min(workers, 24))) as pool:
        futures = {pool.submit(load, model_id): model_id for model_id in ids}
        for future in as_completed(futures):
            model_id = futures[future]
            try:
                _, rows = future.result()
                variants.extend(rows)
            except Exception as exc:
                failures.append({"model_id": model_id, "error": f"Endpoint fetch failed ({type(exc).__name__})"})
    raw_count = len(variants)
    # OpenRouter occasionally emits byte-distinct duplicate endpoint objects
    # with the same model/tag and identical persisted facts.
    variants = list({(row["model_id"], row["provider_tag"]): row for row in variants}.values())
    variants.sort(key=lambda row: (row["model_id"], row["provider_tag"]))
    schema = sorted({key for row in variants for key in row})
    return variants, failures, {
        "models_attempted": len(ids),
        "models_succeeded": len(ids) - len(failures),
        "count": len(variants),
        "raw_count": raw_count,
        "schema_hash": hashlib.sha256(json.dumps(schema).encode()).hexdigest(),
        "url": ENDPOINT_DOCS,
    }


def sync_openrouter_variants(db, variants, failures, manifest, now=None):
    """Upsert exact provider routes and route-specific promotions."""
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    source_id = _source(db, "OpenRouter provider endpoints", ENDPOINT_DOCS)
    provider = db.execute("SELECT id FROM providers WHERE name='OpenRouter'").fetchone()
    if not provider:
        raise ValueError("OpenRouter provider is missing")
    provider_id = provider[0]
    previous_health = db.execute("SELECT schema_hash FROM source_health WHERE source='openrouter-routes'").fetchone()
    schema_changed = bool(previous_health and previous_health[0] and previous_health[0] != manifest.get("schema_hash"))
    imported = changed = 0
    seen = set()
    for row in variants:
        offering = db.execute(
            "SELECT id FROM provider_offerings WHERE provider_id=? AND api_model_id=?",
            (provider_id, row["model_id"]),
        ).fetchone()
        if not offering:
            # The aggregate catalog update owns model identity. Never invent a
            # second canonical model from a provider endpoint.
            continue
        offering_id = offering[0]
        seen.add((offering_id, row["provider_tag"]))
        existing = db.execute(
            "SELECT id,raw_payload_hash,first_seen_at FROM openrouter_route_variants WHERE offering_id=? AND provider_tag=?",
            (offering_id, row["provider_tag"]),
        ).fetchone()
        values = {**row, "offering_id": offering_id, "source_id": source_id, "now": now}
        columns = [
            "upstream_provider","route_name","quantization","endpoint_status","context_limit",
            "max_prompt_tokens","max_output_tokens","tool_support","tool_choice_json",
            "structured_output_support","input_modalities_json","output_modalities_json",
            "input_price","output_price","cache_read_price","cache_write_price","discount_percent",
            "original_input_price","original_output_price","original_price_inferred","is_free",
            "rate_limit_note","model_expires_at","source_id","source_url","raw_payload_hash",
        ]
        if existing:
            if existing["raw_payload_hash"] != row["raw_payload_hash"]:
                changed += 1
            assignments = ",".join(f"{column}=?" for column in columns)
            db.execute(
                f"UPDATE openrouter_route_variants SET {assignments},last_seen_at=?,last_verified_at=? WHERE id=?",
                [*(values[column] for column in columns), now, now, existing["id"]],
            )
            variant_id = existing["id"]
        else:
            inserted = ["offering_id","provider_tag",*columns,"first_seen_at","last_seen_at","last_verified_at"]
            variant_id = db.execute(
                f"INSERT INTO openrouter_route_variants({','.join(inserted)}) VALUES({','.join('?' for _ in inserted)})",
                [offering_id, row["provider_tag"], *(values[column] for column in columns), now, now, now],
            ).lastrowid
            imported += 1
        offer = db.execute(
            "SELECT id,status FROM offers WHERE route_variant_id=? AND offer_type='PROMOTIONAL_DISCOUNT'",
            (variant_id,),
        ).fetchone()
        if row["discount_percent"] > 0:
            status = "ACTIVE" if row["endpoint_status"] == 0 else "UNKNOWN"
            title = f"{row['model_name']} via {row['upstream_provider']} — {row['discount_percent']:g}% off"
            description = "OpenRouter provider-endpoint promotion. Original price is inferred from the API discount fraction when shown."
            offer_values = (
                provider_id, offering_id, variant_id, title, ENDPOINT_DOCS, source_id, status,
                description, now, row["source_url"], row["input_price"], row["output_price"],
                row["original_input_price"], row["original_output_price"], row["discount_percent"],
                row["original_price_inferred"],
            )
            if offer:
                db.execute(
                    """UPDATE offers SET provider_id=?,offering_id=?,route_variant_id=?,title=?,terms_url=?,source_id=?,status=?,
                    description=?,last_verified_at=?,verification_note=?,current_input_price=?,current_output_price=?,
                    original_input_price=?,original_output_price=?,discount_percent=?,original_price_inferred=? WHERE id=?""",
                    (*offer_values, offer["id"]),
                )
            else:
                db.execute(
                    """INSERT INTO offers(provider_id,offering_id,route_variant_id,title,offer_type,terms_url,source_id,status,
                    description,first_seen_at,last_verified_at,verification_note,current_input_price,current_output_price,
                    original_input_price,original_output_price,discount_percent,original_price_inferred)
                    VALUES(?,?,?,?,'PROMOTIONAL_DISCOUNT',?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (*offer_values[:8], now, *offer_values[8:]),
                )
        elif offer and offer["status"] == "ACTIVE":
            db.execute("UPDATE offers SET status='EXPIRED',last_verified_at=? WHERE id=?", (now, offer["id"]))

    # Only a complete endpoint sweep can prove disappearance. Partial failures
    # retain prior rows and offers unchanged.
    complete = not failures and manifest.get("models_attempted") == manifest.get("models_succeeded")
    if complete:
        for stale in db.execute("SELECT id,offering_id,provider_tag FROM openrouter_route_variants").fetchall():
            if (stale["offering_id"], stale["provider_tag"]) not in seen:
                db.execute("UPDATE openrouter_route_variants SET endpoint_status=-2 WHERE id=?", (stale["id"],))
                db.execute("UPDATE offers SET status='EXPIRED',last_verified_at=? WHERE route_variant_id=? AND status='ACTIVE'", (now, stale["id"]))

    status = "ERROR" if failures else "SCHEMA_CHANGED" if schema_changed else "OK"
    db.execute(
        """INSERT INTO source_health(source,source_url,last_attempt_at,last_success_at,status,records_imported,records_changed,error,schema_hash,schema_changed_at,response_note)
        VALUES('openrouter-routes',?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source) DO UPDATE SET source_url=excluded.source_url,last_attempt_at=excluded.last_attempt_at,
        last_success_at=excluded.last_success_at,status=excluded.status,records_imported=excluded.records_imported,
        records_changed=excluded.records_changed,error=excluded.error,schema_hash=excluded.schema_hash,
        schema_changed_at=COALESCE(excluded.schema_changed_at,source_health.schema_changed_at),response_note=excluded.response_note""",
        (
            ENDPOINT_DOCS, now, None if failures else now, status, len(variants), changed,
            (f"{len(failures)} model endpoint fetches failed: " + ", ".join(item['model_id'] for item in failures[:10])) if failures else None,
            manifest.get("schema_hash"), now if schema_changed else None,
            f"{manifest.get('models_succeeded', 0)}/{manifest.get('models_attempted', 0)} models; {len(variants)} endpoints",
        ),
    )
    return {"imported": imported, "changed": changed, "failures": len(failures), "complete": complete}

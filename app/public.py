"""Public read-only API, discovery feeds, and crawler policy."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape

from flask import Blueprint, Response, abort, jsonify, request, url_for

from .db import get_db
from .domain import compatibility_for
from .query import offer_rows, route_rows

public = Blueprint("public", __name__)
API_VERSION = "v1"
TRUE_VALUES = {"1", "true", "yes", "on"}


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _truth(value) -> bool:
    return str(value or "").lower() in TRUE_VALUES


def _envelope(data, **meta):
    count = len(data) if isinstance(data, list) else (1 if data is not None else 0)
    return jsonify({"data": data, "meta": {"api_version": API_VERSION, "count": count, **meta}})


def _source(row):
    return ({"name": row["source_name"], "url": row["source_url"]}
            if row.get("source_url") else None)


def _route_json(row, compatibility=None):
    media_prices = [dict(price) for price in get_db().execute("""SELECT price_type,amount,currency,unit,
      context_threshold,valid_from,price_note,promotional FROM pricing_records WHERE offering_id=?
      AND valid_until IS NULL AND price_type NOT IN ('INPUT','OUTPUT','CACHE_READ','CACHE_WRITE','BATCH_INPUT','BATCH_OUTPUT')
      ORDER BY price_type,unit,context_threshold""", (row["offering_id"],))]
    result = {
        "id": row["offering_id"],
        "api_model_id": row["api_model_id"],
        "model": {"id": row["model_id"], "name": row["canonical_name"],
                  "slug": row["canonical_slug"], "type": row["modality"],
                  "open_weights": bool(row["open_weights"]), "status": row["status"],
                  "release_date": row["released_at"]},
        "provider": {"id": row["provider_id"], "name": row["provider_name"],
                     "slug": slugify(row["provider_name"])},
        "limits": {"context": row["context_limit"], "max_output": row["max_output_tokens"]},
        "capabilities": {"tools": row["tool_support"],
                         "structured_output": row["structured_output_support"],
                         "reasoning": "YES" if row["reasoning"] else "UNKNOWN",
                         "vision": "YES" if row["vision"] else "UNKNOWN",
                         "caching": "YES" if row["caching"] else "UNKNOWN",
                         "batch": "YES" if row["batch"] else "UNKNOWN"},
        "pricing": {
            "input_per_million_tokens": row["input_price"],
            "output_per_million_tokens": row["output_price"],
            "cache_read_per_million_tokens": row["cache_read_price"],
            "media": ({"amount": row["media_price"], "unit": row["media_price_unit"],
                       "type": row["media_price_type"]} if row["media_price"] is not None else None),
            "media_prices": media_prices,
            "currency": "USD",
        },
        "free_status": row["free_status"],
        "active_offer": bool(row["active_deal"]),
        "commercial_use": row["commercial_use"],
        "caveats": {"general": row["caveat"], "rate_limit": row["rate_limit_note"],
                    "privacy": row["privacy_caveat"]},
        "first_seen_at": row["first_seen_at"],
        "last_verified_at": row["fetched_at"],
        "source": ({"name": row["route_source_name"], "url": row["route_source_url"]}
                   if row["route_source_url"] else None),
        "url": url_for("route_detail_slug", provider_slug=slugify(row["provider_name"]),
                       api_model_id=row["api_model_id"], _external=True),
    }
    if compatibility:
        result["compatibility"] = compatibility
    return result


def normalized_filters(args):
    """Accept stable API names while sharing the catalogue's query engine."""
    values = {key: value for key, value in args.items() if value not in ("", None)}
    aliases = {
        "max_input_price": "input_max",
        "max_output_price": "output_max",
        "min_context": "context",
        "min_output": "max_output",
    }
    for public_name, internal in aliases.items():
        if public_name in values and internal not in values:
            values[internal] = values[public_name]
    for key in ("tools", "mcp", "free", "open_weights", "commercial", "reasoning",
                "vision", "caching", "batch", "text_to_3d", "image_to_3d"):
        if key in values:
            values[key] = "1" if _truth(values[key]) else "0"
    if values.get("type", "").lower() == "3d":
        values["type"] = "3D generation"
    if values.get("offers") == "current":
        values["deal"] = "1"
    if values.get("releases") in {"7-days", "week", "7d"}:
        values["release"] = "week"
    return values


def _harness(value):
    if not value:
        return None
    db = get_db()
    rows = db.execute("SELECT * FROM harnesses").fetchall()
    wanted = str(value).lower()
    # Public shorthand kept stable even when the display name is more specific.
    wanted = {"hermes": "hermes-agent"}.get(wanted, wanted)
    return next((row for row in rows if str(row["id"]) == wanted or
                 row["name"].lower() == wanted or slugify(row["name"]) == wanted), None)


def filtered_routes(args):
    filters = normalized_filters(args)
    harness = _harness(filters.get("harness"))
    if filters.get("harness") and not harness:
        return [], filters
    filters.pop("harness", None)
    try:
        requested_limit = min(250, max(1, int(filters.get("limit", 100))))
    except (TypeError, ValueError):
        requested_limit = 100
    needs_compatibility = bool(harness or filters.get("mcp") == "1")
    candidates = route_rows(get_db(), {**filters, "limit": 10_000} if needs_compatibility else filters)
    if not harness and filters.get("mcp") == "1":
        # MCP is a workflow property: require at least one documented MCP harness route.
        mcp_harnesses = get_db().execute("SELECT id FROM harnesses WHERE supports_mcp=1").fetchall()
        return [row for row in candidates if any(
            compatibility_for(get_db(), h["id"], row["offering_id"], True)["status"]
            in {"COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION", "PARTIAL"}
            for h in mcp_harnesses)][:requested_limit], filters
    if harness:
        kept = []
        for row in candidates:
            match = compatibility_for(get_db(), harness["id"], row["offering_id"], filters.get("mcp") == "1")
            if match["status"] in {"COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION", "PARTIAL"}:
                kept.append({**row, "_compatibility": match})
        return kept[:requested_limit], filters
    return candidates, filters


@public.get("/api/v1")
def api_index():
    return _envelope({
        "name": "UseThisModel public read-only API",
        "documentation": url_for("public.api_docs", _external=True),
        "response": {"data": "resource or list", "meta": {"api_version": "v1", "count": "integer"}},
        "endpoints": ["models", "models/{canonical-slug}", "providers", "harnesses",
                      "offers", "releases", "benchmarks", "compatibility", "search"],
    })


@public.get("/api")
def api_docs():
    return Response("""<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width'>
<title>Public API — UseThisModel</title><body><main><h1>UseThisModel public API v1</h1>
<p>All endpoints are read-only JSON. Responses use <code>{&quot;data&quot;: …, &quot;meta&quot;: {&quot;api_version&quot;: &quot;v1&quot;, &quot;count&quot;: …}}</code>. Unknown values remain null or the explicit tri-state <code>UNKNOWN</code>.</p>
<h2>Resources</h2><ul><li><code>GET /api/v1/models</code> and <code>/api/v1/models/{canonical-slug}</code></li><li><code>GET /api/v1/providers</code></li><li><code>GET /api/v1/harnesses</code></li><li><code>GET /api/v1/offers?status=current</code></li><li><code>GET /api/v1/releases?window=7-days</code></li><li><code>GET /api/v1/benchmarks</code></li><li><code>GET /api/v1/compatibility?harness=hermes-agent&amp;mcp=true</code></li><li><code>GET /api/v1/search?q=coding</code></li></ul>
<h2>Model and search filters</h2><p><code>tools=true</code>, <code>max_output_price=1</code>, <code>harness=hermes-agent</code>, <code>mcp=true</code>, <code>offers=current</code>, <code>releases=7-days</code>, <code>type=3d</code>, <code>provider=OpenRouter</code>, <code>min_context=1000000</code>, <code>free=true</code>, <code>open_weights=true</code>, and <code>limit=100</code> can be combined. Prices are USD per million tokens unless a media price includes a native unit.</p>
<p><a href=/api/v1>Machine-readable API index</a> · <a href=/>UseThisModel</a></p></main></body></html>""", mimetype="text/html")


@public.get("/api/v1/models")
def api_models():
    routes, filters = filtered_routes(request.args)
    grouped = {}
    for route in routes:
        model = grouped.setdefault(route["model_id"], {
            "id": route["model_id"], "name": route["canonical_name"],
            "slug": route["canonical_slug"], "lab": route["lab_name"],
            "type": route["modality"], "open_weights": bool(route["open_weights"]),
            "status": route["status"], "release_date": route["released_at"], "routes": []})
        model["routes"].append(_route_json(route, route.get("_compatibility")))
    return _envelope(list(grouped.values()), filters=filters)


@public.get("/api/v1/models/<path:slug>")
def api_model(slug):
    row = get_db().execute("SELECT id FROM models WHERE canonical_slug=?", (slug,)).fetchone()
    if not row:
        abort(404)
    routes = route_rows(get_db(), {"model_id": row["id"], "limit": 1000})
    first = routes[0] if routes else get_db().execute("SELECT * FROM models WHERE id=?", (row["id"],)).fetchone()
    model = {"id": row["id"], "name": first["canonical_name"], "slug": first["canonical_slug"],
             "type": first["modality"], "open_weights": bool(first["open_weights"]),
             "status": first["status"], "release_date": first["released_at"],
             "routes": [_route_json(route) for route in routes]}
    return _envelope(model)


@public.get("/api/v1/providers")
def api_providers():
    records = [dict(row) for row in get_db().execute("""SELECT p.id,p.name,p.website_url,
      COUNT(o.id) route_count,MAX(o.fetched_at) last_verified_at FROM providers p
      LEFT JOIN provider_offerings o ON o.provider_id=p.id GROUP BY p.id ORDER BY p.name""")]
    for row in records:
        row["slug"] = slugify(row["name"])
    return _envelope(records)


@public.get("/api/v1/harnesses")
def api_harnesses():
    data = []
    for row in get_db().execute("SELECT * FROM harnesses ORDER BY name"):
        item = {key: row[key] for key in row.keys() if key not in {"source_id"}}
        item["slug"] = slugify(row["name"])
        item["mcp_capabilities"] = [dict(x) for x in get_db().execute(
            "SELECT transport,state,note FROM harness_mcp_capabilities WHERE harness_id=? ORDER BY transport", (row["id"],))]
        data.append(item)
    return _envelope(data)


@public.get("/api/v1/offers")
def api_offers():
    include_expired = request.args.get("status") not in {None, "current", "active"}
    return _envelope(offer_rows(get_db(), include_expired=include_expired),
                     status="all" if include_expired else "current")


@public.get("/api/v1/releases")
def api_releases():
    window = request.args.get("window", "7-days")
    days = 7
    match = re.fullmatch(r"(\d+)-days", window)
    if match:
        days = min(365, max(1, int(match.group(1))))
    since = (date.today() - timedelta(days=days)).isoformat()
    data = [dict(row) for row in get_db().execute("""SELECT id,canonical_name name,canonical_slug slug,
      modality type,released_at release_date,release_date_kind,status FROM models
      WHERE released_at IS NOT NULL AND released_at>=? ORDER BY released_at DESC,canonical_name""", (since,))]
    return _envelope(data, window=f"{days}-days", since=since)


@public.get("/api/v1/benchmarks")
def api_benchmarks():
    data = []
    for row in get_db().execute("SELECT b.*,s.name source_name,s.url source_url FROM benchmarks b LEFT JOIN sources s ON s.id=b.source_id ORDER BY b.name,b.version"):
        item = dict(row)
        item["slug"] = slugify(f"{row['name']}-{row['version']}")
        item["source"] = _source(item)
        item.pop("source_id", None)
        item.pop("source_name", None)
        item.pop("source_url", None)
        item["results"] = [dict(x) for x in get_db().execute("""SELECT m.canonical_name model,m.canonical_slug model_slug,
          br.score,br.metric,br.harness_name,br.scaffold,br.reasoning_setting,br.evaluated_at,br.confidence
          FROM benchmark_results br JOIN models m ON m.id=br.model_id WHERE br.benchmark_id=? ORDER BY br.score DESC""", (row["id"],))]
        data.append(item)
    return _envelope(data)


@public.get("/api/v1/compatibility")
def api_compatibility():
    harness = _harness(request.args.get("harness"))
    if not harness:
        return jsonify({"error": {"code": "invalid_harness", "message": "A known harness id, name, or slug is required."}}), 400
    routes, filters = filtered_routes(request.args)
    data = [_route_json(row, row.get("_compatibility") or compatibility_for(
        get_db(), harness["id"], row["offering_id"], filters.get("mcp") == "1")) for row in routes]
    return _envelope(data, harness={"id": harness["id"], "name": harness["name"], "slug": slugify(harness["name"])})


@public.get("/api/v1/search")
def api_search():
    routes, filters = filtered_routes(request.args)
    return _envelope([_route_json(row, row.get("_compatibility")) for row in routes], filters=filters)


@public.get("/robots.txt")
def robots():
    root = request.url_root.rstrip("/")
    return Response(f"User-agent: *\nAllow: /\nDisallow: /models?\nDisallow: /compare?\nDisallow: /calculator?\nSitemap: {root}/sitemap.xml\n", mimetype="text/plain")


@public.get("/sitemap.xml")
def sitemap():
    root = request.url_root.rstrip("/")
    urls = ["/", "/models", "/providers", "/harnesses", "/benchmarks", "/use-cases", "/offers", "/rankings", "/api"]
    urls += ["/models/" + row[0] for row in get_db().execute("SELECT canonical_slug FROM models WHERE canonical_slug IS NOT NULL")]
    urls += ["/providers/" + slugify(row[0]) for row in get_db().execute("SELECT name FROM providers")]
    urls += ["/harnesses/" + slugify(row[0]) for row in get_db().execute("SELECT name FROM harnesses")]
    urls += ["/benchmarks/" + slugify(f"{row[0]}-{row[1]}") for row in get_db().execute("SELECT name,version FROM benchmarks")]
    urls += ["/use-cases/" + row[0] for row in get_db().execute("SELECT slug FROM use_cases")]
    body = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">" + "".join(
        f"<url><loc>{root}{path}</loc></url>" for path in urls) + "</urlset>"
    return Response(body, mimetype="application/xml")


def _feed(title, path, entries):
    root = request.url_root.rstrip("/")
    updated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    items = "".join(f"<entry><id>{escape(root + url)}</id><title>{escape(str(name))}</title><link href=\"{escape(root + url)}\"/><updated>{escape(str(when))}T00:00:00Z</updated><summary>{escape(str(summary))}</summary></entry>" for name, url, when, summary in entries)
    body = f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><feed xmlns=\"http://www.w3.org/2005/Atom\"><id>{root}{path}</id><title>{title}</title><updated>{updated}</updated><link href=\"{root}{path}\" rel=\"self\"/>{items}</feed>"
    return Response(body, mimetype="application/atom+xml")


@public.get("/feeds/releases.atom")
def release_feed():
    entries = [(row["canonical_name"], "/models/" + row["canonical_slug"], row["released_at"][:10],
                f"{row['modality']} model from {row['vendor']}; release date provenance: {row['release_date_kind']}.")
               for row in get_db().execute("SELECT * FROM models WHERE released_at IS NOT NULL ORDER BY released_at DESC LIMIT 50")]
    return _feed("UseThisModel new model releases", "/feeds/releases.atom", entries)


@public.get("/feeds/price-changes.atom")
def price_feed():
    rows = get_db().execute("""SELECT pr.valid_from,m.canonical_name,m.canonical_slug,p.name provider,
      pr.price_type,pr.amount,pr.unit FROM pricing_records pr JOIN provider_offerings o ON o.id=pr.offering_id
      JOIN models m ON m.id=o.model_id JOIN providers p ON p.id=o.provider_id
      WHERE EXISTS(SELECT 1 FROM pricing_records old WHERE old.offering_id=pr.offering_id
        AND old.price_type=pr.price_type AND old.id!=pr.id) ORDER BY pr.valid_from DESC LIMIT 50""").fetchall()
    entries = [(f"{r['canonical_name']} via {r['provider']}: {r['price_type']}", "/models/" + r["canonical_slug"],
                r["valid_from"][:10], f"Recorded price: USD {r['amount']} {r['unit']}.") for r in rows]
    return _feed("UseThisModel price changes", "/feeds/price-changes.atom", entries)

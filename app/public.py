"""Public read-only API, discovery feeds, and crawler policy."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from xml.sax.saxutils import escape

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    jsonify,
    make_response,
    redirect,
    request,
    url_for,
)

from .db import get_db
from .domain import compatibility_for
from .query import (
    access_route_rows,
    modality_category,
    normalize_context,
    offer_rows,
    plan_rows,
    route_rows,
)

public = Blueprint("public", __name__)
API_VERSION = "v1"
TRUE_VALUES = {"1", "true", "yes", "on"}


def public_origin() -> str:
    """Return the configured canonical origin without trusting an arbitrary Host header."""
    return (current_app.config.get("PUBLIC_BASE_URL") or request.url_root).rstrip("/")


def absolute_url(path: str) -> str:
    return public_origin() + (path if path.startswith("/") else "/" + path)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _truth(value) -> bool:
    return str(value or "").lower() in TRUE_VALUES


def _envelope(data, **meta):
    count = len(data) if isinstance(data, list) else (1 if data is not None else 0)
    return jsonify({"data": data, "meta": {"api_version": API_VERSION, "count": count, **meta}})


def _api_page(items, args=None):
    """Apply the v1 offset pagination contract to a complete matching list."""
    args = args or request.args
    try:
        limit = int(args.get("limit", 100))
        if limit < 1:
            raise ValueError
        limit = min(250, limit)
        if "page" in args and "offset" in args:
            raise ValueError
        if "page" in args:
            page = int(args["page"])
            if page < 1:
                raise ValueError
            offset = (page - 1) * limit
        else:
            offset = int(args.get("offset", 0))
            if offset < 0:
                raise ValueError
    except (TypeError, ValueError):
        return None, ({"error": {"code": "invalid_pagination", "message":
                "Use limit=1..250 with either a positive 1-based page or a non-negative offset."}}, 400)
    total = len(items)
    data = items[offset:offset + limit]
    next_offset = offset + limit if offset + len(data) < total else None
    previous_offset = max(0, offset - limit) if offset else None
    return (data, {"total": total, "limit": limit, "offset": offset,
                   "next_offset": next_offset, "previous_offset": previous_offset,
                   "has_more": next_offset is not None}), None


def _paged_envelope(items, **meta):
    page, error = _api_page(items)
    if error:
        return jsonify(error[0]), error[1]
    data, pagination = page
    response = _envelope(data, **pagination, **meta)
    response.set_etag(sha256(response.get_data()).hexdigest(), weak=False)
    response.headers.setdefault("Cache-Control", "public, max-age=60, stale-while-revalidate=30")
    return response.make_conditional(request)


def _unpaged_args():
    return {key: value for key, value in request.args.items()
            if key not in {"limit", "offset", "page"}}


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
                  "slug": row["canonical_slug"], "type": modality_category(row["modality"], row["canonical_name"]),
                  "modality_category": modality_category(row["modality"], row["canonical_name"]), "raw_modality": row["modality"],
                  "open_weights": bool(row["open_weights"]), "status": row["status"],
                  "release_date": row["released_at"], "identity_kind": row["identity_kind"],
                  "identity_status": "UNRESOLVED" if row["identity_kind"] == "UNKNOWN" else "VERIFIED"},
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
        "access_semantics": row["access_semantics"],
        "access_requirement": row["access_requirement"],
        "active_offer": bool(row["active_deal"]),
        "commercial_use": row["commercial_use"],
        "caveats": {"general": row["caveat"], "rate_limit": row["rate_limit_note"],
                    "privacy": row["privacy_caveat"]},
        "first_seen_at": row["first_seen_at"],
        "last_verified_at": row["last_verified_at"] or row["fetched_at"],
        "lifecycle_status": row["lifecycle_status"],
        "source": ({"name": row["route_source_name"], "url": row["route_source_url"]}
                   if row["route_source_url"] else None),
        "url": absolute_url(url_for("route_detail_slug", provider_slug=slugify(row["provider_name"]),
                                    api_model_id=row["api_model_id"])),
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
    for key in ("tools", "mcp", "free", "included", "open_weights", "commercial", "reasoning",
                "vision", "caching", "batch", "text_to_3d", "image_to_3d"):
        if key in values:
            values[key] = "1" if _truth(values[key]) else "0"
    if values.get("type", "").lower() == "3d":
        values["type"] = "3D generation"
    if "context" in values:
        values["context"] = str(normalize_context(values["context"]))
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
    try:
        filters = normalized_filters(args)
    except ValueError as exc:
        return [], {"filter_errors": [str(exc)], **{k: v for k, v in args.items()}}
    harness = _harness(filters.get("harness"))
    if filters.get("harness") and not harness:
        filters["filter_errors"] = [f"Unknown harness: {filters['harness']}"]
        return [], filters
    filters.pop("harness", None)
    workflow = None
    if filters.get("workflow"):
        workflow = get_db().execute(
            "SELECT id,slug,name FROM workflows WHERE slug=? OR name=?",
            (filters["workflow"], filters["workflow"]),
        ).fetchone()
        if not workflow:
            filters["filter_errors"] = [f"Unknown workflow: {filters['workflow']}"]
            return [], filters
    route_filters = {key: value for key, value in filters.items() if key != "workflow"}
    try:
        requested_limit = min(100_000, max(1, int(filters.get("limit", 100))))
    except (TypeError, ValueError):
        requested_limit = 100
    try:
        requested_offset = min(10_000, max(0, int(filters.get("offset", 0))))
    except (TypeError, ValueError):
        requested_offset = 0
    needs_compatibility = bool(harness or route_filters.get("mcp") == "1" or workflow)
    try:
        candidates = route_rows(get_db(), {**route_filters, "limit": 100_000, "offset": 0}
                                if needs_compatibility else
                                {**route_filters, "limit": requested_limit, "offset": requested_offset})
    except ValueError as exc:
        filters["filter_errors"] = [str(exc)]
        return [], filters
    if not harness and filters.get("mcp") == "1":
        # MCP is a workflow property: require at least one documented MCP harness route.
        mcp_harnesses = get_db().execute("SELECT id FROM harnesses WHERE supports_mcp=1").fetchall()
        matches = [row for row in candidates if any(
            compatibility_for(get_db(), h["id"], row["offering_id"], True)["status"]
            in {"COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION", "PARTIAL"}
            for h in mcp_harnesses)]
        return matches[requested_offset:requested_offset + requested_limit], filters
    if harness:
        kept = []
        for row in candidates:
            match = compatibility_for(
                get_db(), harness["id"], row["offering_id"],
                route_filters.get("mcp") == "1" or workflow is not None,
                workflow["id"] if workflow else None,
            )
            if match["status"] in {"COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION", "PARTIAL"}:
                kept.append({**row, "_compatibility": match})
        return kept[requested_offset:requested_offset + requested_limit], filters
    return candidates, filters


@public.get("/api/v1")
def api_index():
    return _envelope({
        "name": "UseThisModel public read-only API",
        "documentation": absolute_url(url_for("public.api_docs")),
        "openapi": absolute_url(url_for("public.openapi_spec")),
        "response": {"data": "resource or list", "meta": {"api_version": "v1", "count": "page size", "total": "matching records", "limit": 100, "offset": 0, "next_offset": "integer or null", "has_more": "boolean"}},
        "endpoints": ["models", "models/{canonical-slug}", "providers", "plans", "access-routes", "harnesses", "workflows",
                      "offers", "free-routes", "releases", "benchmarks", "compatibility", "search"],
    })


@public.get("/api")
def api_docs():
    canonical = absolute_url("/api")
    body = """<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width'>
<meta name=description content="Read-only, source-backed UseThisModel API for AI models, provider routes, prices, offers, benchmarks, and harness compatibility."><meta name=robots content="index,follow"><link rel=canonical href="__CANONICAL__"><title>Public API — UseThisModel</title></head><body><nav aria-label="Site"><a href=/>UseThisModel</a> · <a href=/models>Models</a> · <a href=/providers>Providers</a> · <a href=/harnesses>Harnesses</a></nav><main><h1>UseThisModel public API v1</h1>
<p>All endpoints are read-only JSON. Collections accept <code>limit</code> (default 100, maximum 250) and either 1-based <code>page</code> or zero-based <code>offset</code>. Do not combine page and offset. Metadata <code>count</code> is this page’s size; <code>total</code> is the total matching records; <code>next_offset</code> is null at the end; <code>has_more</code> states whether another page exists. Oversized limits are capped; malformed pagination is rejected with HTTP 400. Unfiltered machine collections include their full catalog, regardless of featured web subsets.</p>
<h2>Resources</h2><ul><li><code>GET /api/v1/models</code> and <code>/api/v1/models/{canonical-slug}</code></li><li><code>GET /api/v1/providers</code></li><li><code>GET /api/v1/harnesses</code></li><li><code>GET /api/v1/offers?status=current</code></li><li><code>GET /api/v1/free-routes?tools=true</code></li><li><code>GET /api/v1/releases</code> (all dated releases; use <code>?window=7-days</code> for recent releases or <code>?window=all</code> explicitly)</li><li><code>GET /api/v1/benchmarks</code></li><li><code>GET /api/v1/compatibility?harness=hermes-agent&amp;mcp=true</code></li><li><code>GET /api/v1/search?q=coding</code></li></ul>
<h2>Model and search filters</h2><p><code>tools=true</code>, <code>max_output_price=1</code>, <code>harness=hermes-agent</code>, <code>mcp=true</code>, <code>offers=current</code>, <code>releases=7-days</code>, <code>type=3d</code>, <code>provider=OpenRouter</code>, <code>min_context=1000000</code>, <code>free=true</code>, <code>open_weights=true</code>, and <code>limit=100</code> can be combined. Prices are USD per million tokens unless a media price includes a native unit.</p>
<p><a href=/api/v1/openapi.json>OpenAPI 3.1 description</a> · <a href=/api/v1>Machine-readable API index</a> · <a href=/>UseThisModel</a></p></main></body></html>"""
    return Response(body.replace("__CANONICAL__", canonical), mimetype="text/html")


@public.get("/api/v1/openapi.json")
def openapi_spec():
    """Generate discovery paths from Flask's live route map so the document cannot drift."""
    paths = {}
    for rule in current_app.url_map.iter_rules():
        if not rule.rule.startswith("/api/v1") or "GET" not in rule.methods:
            continue
        path = re.sub(r"<(?:[^:>]+:)?([^>]+)>", r"{\1}", rule.rule)
        parameters = [
            {"name": argument, "in": "path", "required": True,
             "schema": {"type": "string"}}
            for argument in sorted(rule.arguments)
        ]
        if rule.rule.startswith("/api/v1/") and "<" not in rule.rule:
            parameters.extend([
                {"name":"limit","in":"query","schema":{"type":"integer","minimum":1,"maximum":250,"default":100}},
                {"name":"page","in":"query","schema":{"type":"integer","minimum":1},"description":"1-based; mutually exclusive with offset."},
                {"name":"offset","in":"query","schema":{"type":"integer","minimum":0},"description":"Zero-based; mutually exclusive with page."},
            ])
        paths[path] = {"get": {
            "operationId": rule.endpoint.replace(".", "_"),
            "summary": (current_app.view_functions[rule.endpoint].__doc__ or
                        rule.endpoint.rsplit(".", 1)[-1].replace("_", " ").title()).strip(),
            **({"parameters": parameters} if parameters else {}),
            "responses": {"200": {"description": "Successful read-only response"}},
        }}
    return jsonify({
        "openapi": "3.1.0",
        "info": {"title": "UseThisModel public read-only API", "version": API_VERSION,
                 "description": "Source-backed AI model, provider-route, pricing, offer, benchmark and harness compatibility data."},
        "servers": [{"url": public_origin()}],
        "paths": dict(sorted(paths.items())),
    })


@public.get("/api/v1/models")
def api_models():
    public_filters = _unpaged_args()
    filters_in = dict(public_filters)
    filters_in.update(limit=100000, offset=0)
    routes, filters = filtered_routes(filters_in)
    grouped = {}
    for route in routes:
        model = grouped.setdefault(route["model_id"], {
            "id": route["model_id"], "name": route["canonical_name"],
            "slug": route["canonical_slug"], "lab": route["lab_name"],
            "type": modality_category(route["modality"], route["canonical_name"]),
            "modality_category": modality_category(route["modality"], route["canonical_name"]), "raw_modality": route["modality"],
            "open_weights": bool(route["open_weights"]),
            "status": route["status"], "release_date": route["released_at"],
            "identity_kind": route["identity_kind"],
            "identity_status": "UNRESOLVED" if route["identity_kind"] == "UNKNOWN" else "VERIFIED",
            "routes": []})
        model["routes"].append(_route_json(route, route.get("_compatibility")))
    if not public_filters:
        for row in get_db().execute("""SELECT m.id,m.canonical_name name,m.canonical_slug slug,
          COALESCE(l.name,m.vendor) lab,m.modality,m.open_weights,m.status,m.released_at,m.identity_kind
          FROM models m LEFT JOIN labs l ON l.id=m.lab_id ORDER BY m.canonical_name"""):
            grouped.setdefault(row["id"], {"id":row["id"],"name":row["name"],"slug":row["slug"],
              "lab":row["lab"],"type":modality_category(row["modality"],row["name"]),
              "modality_category":modality_category(row["modality"],row["name"]),"raw_modality":row["modality"],
              "open_weights":bool(row["open_weights"]),"status":row["status"],
              "release_date":row["released_at"],"identity_kind":row["identity_kind"],
              "identity_status":"UNRESOLVED" if row["identity_kind"] == "UNKNOWN" else "VERIFIED",
              "routes":[]})
    return _paged_envelope(list(grouped.values()), filters=filters)


@public.get("/api/v1/models/<path:slug>")
def api_model(slug):
    row = get_db().execute("SELECT id FROM models WHERE canonical_slug=?", (slug,)).fetchone()
    if not row:
        target = get_db().execute(
            """SELECT m.canonical_slug FROM model_identity_redirects r
               JOIN models m ON m.id=r.target_model_id WHERE r.old_slug=?""",
            (slug,),
        ).fetchone()
        if target:
            return redirect(url_for("public.api_model", slug=target[0]), code=301)
        abort(404)
    routes = route_rows(get_db(), {"model_id": row["id"], "limit": 100000})
    first = routes[0] if routes else get_db().execute("SELECT * FROM models WHERE id=?", (row["id"],)).fetchone()
    model = {"id": row["id"], "name": first["canonical_name"], "slug": first["canonical_slug"],
             "type": modality_category(first["modality"]), "modality_category": modality_category(first["modality"]),
             "raw_modality": first["modality"], "open_weights": bool(first["open_weights"]),
             "status": first["status"], "release_date": first["released_at"],
             "identity_kind": first["identity_kind"],
             "identity_status": "UNRESOLVED" if first["identity_kind"] == "UNKNOWN" else "VERIFIED",
             "routes": [_route_json(route) for route in routes]}
    return _envelope(model)


@public.get("/api/v1/providers")
def api_providers():
    records = [dict(row) for row in get_db().execute("""SELECT p.id,p.name,p.website_url,
      COUNT(o.id) route_count,MAX(COALESCE(o.last_verified_at,o.fetched_at)) last_verified_at FROM providers p
      LEFT JOIN providers alias ON alias.canonical_provider_id=p.id
      LEFT JOIN provider_offerings o ON o.provider_id IN (p.id,alias.id)
      WHERE p.canonical_provider_id IS NULL GROUP BY p.id ORDER BY p.name""")]
    for row in records:
        row["slug"] = slugify(row["name"])
    return _paged_envelope(records)


@public.get("/api/v1/plans")
def api_plans():
    filters = normalized_filters(_unpaged_args())
    for key in ("coding", "api", "subscription"):
        if key in filters:
            filters[key] = "1" if _truth(filters[key]) else "0"
    return _paged_envelope(plan_rows(get_db(), filters), filters=filters)


@public.get("/api/v1/access-routes")
def api_access_routes():
    return _paged_envelope(access_route_rows(get_db()))


@public.get("/api/v1/harnesses")
def api_harnesses():
    data = []
    for row in get_db().execute("SELECT * FROM harnesses ORDER BY name"):
        item = {key: row[key] for key in row.keys() if key not in {"source_id"}}
        item["slug"] = slugify(row["name"])
        item["mcp_capabilities"] = [dict(x) for x in get_db().execute(
            "SELECT transport,state,note FROM harness_mcp_capabilities WHERE harness_id=? ORDER BY transport", (row["id"],))]
        item["claims"] = [dict(x) for x in get_db().execute(
            """SELECT hc.claim_key,hc.claim_value,hc.note,hc.verified_at,s.url source_url,
                      dm.status documentation_status,dm.last_checked_at documentation_last_checked_at,
                      dm.last_changed_at documentation_last_changed_at
               FROM harness_claims hc JOIN sources s ON s.id=hc.source_id
               LEFT JOIN documentation_monitor_state dm ON dm.source_id=hc.source_id
               WHERE hc.harness_id=? ORDER BY hc.claim_key""", (row["id"],))]
        item["access_methods"] = [dict(x) for x in get_db().execute(
            """SELECT ha.access_method,ha.state,ha.note,ha.verified_at,s.url source_url,
                      dm.status documentation_status,dm.last_checked_at documentation_last_checked_at,
                      dm.last_changed_at documentation_last_changed_at
               FROM harness_access_methods ha JOIN sources s ON s.id=ha.source_id
               LEFT JOIN documentation_monitor_state dm ON dm.source_id=ha.source_id
               WHERE ha.harness_id=? ORDER BY ha.access_method""", (row["id"],))]
        data.append(item)
    return _paged_envelope(data)


@public.get("/api/v1/workflows")
def api_workflows():
    data = []
    for row in get_db().execute("SELECT * FROM workflows ORDER BY name"):
        item = dict(row)
        item["integrations"] = [dict(x) for x in get_db().execute(
            """SELECT wi.name,wi.repository_url,wi.transport,wi.os_requirements,wi.locality,wi.tools_exposed,
              wi.maintenance_status,wi.maintenance_note,wi.verified_at,
              dm.status documentation_status,dm.last_checked_at documentation_last_checked_at,
              dm.last_changed_at documentation_last_changed_at
              FROM workflow_integrations wi LEFT JOIN documentation_monitor_state dm ON dm.source_id=wi.source_id
              WHERE wi.workflow_id=? ORDER BY wi.name""", (row["id"],))]
        data.append(item)
    return _paged_envelope(data)


@public.get("/api/v1/offers")
def api_offers():
    include_expired = request.args.get("status") not in {None, "current", "active"}
    return _paged_envelope(offer_rows(get_db(), include_expired=include_expired),
                     status="all" if include_expired else "current")


@public.get("/api/v1/free-routes")
def api_free_routes():
    tools_only = _truth(request.args.get("tools"))
    filters = _unpaged_args()
    filters.pop("tools", None)
    filters["free"] = "1"
    provider_name = request.args.get("provider")
    if provider_name and not get_db().execute(
            "SELECT 1 FROM providers WHERE lower(name)=lower(?) AND canonical_provider_id IS NULL", (provider_name,)).fetchone():
        return jsonify({"error": {"code": "invalid_provider", "message": "Unknown provider filter."}}), 400
    if tools_only:
        filters["tools"] = "1"
    try:
        routes = route_rows(get_db(), {**filters, "limit": 100000, "offset": 0})
    except ValueError as exc:
        return jsonify({"error": {"code": "invalid_filter", "message": str(exc)}}), 400
    return _paged_envelope([_route_json(row) for row in routes],
                           provider=request.args.get("provider"), tools=tools_only,
                           definition="Public free API/free-tier routes only; subscription-included routes are excluded.")


@public.get("/api/v1/releases")
def api_releases():
    window = request.args.get("window", "all")
    if window == "all":
        since = None
    else:
        match = re.fullmatch(r"(\d+)-days", window)
        if not match or not 1 <= int(match.group(1)) <= 365:
            return jsonify({"error":{"code":"invalid_window","message":"Use window=all or window=<1..365>-days."}}), 400
        days = int(match.group(1))
        since = (date.today() - timedelta(days=days)).isoformat()
    release_where = "released_at IS NOT NULL" + (" AND released_at>=?" if since else "")
    params = (since,) if since else ()
    data = [dict(row) for row in get_db().execute("""SELECT id,canonical_name name,canonical_slug slug,
      modality raw_modality,released_at release_date,release_date_kind status_kind,status FROM models
      WHERE """ + release_where + " ORDER BY released_at DESC,canonical_name", params)]
    for row in data:
        row["modality_category"] = row["type"] = modality_category(row["raw_modality"], row["name"])
        row["release_date_confidence"] = {"official":"Official","publisher_metadata":"Publisher metadata","aggregator":"Aggregator"}.get(row.pop("status_kind"), "Unverified")
        row["routes_count"] = get_db().execute("SELECT COUNT(*) FROM provider_offerings WHERE model_id=?", (row["id"],)).fetchone()[0]
    return _paged_envelope(data, window=window, since=since)


@public.get("/api/v1/benchmarks")
def api_benchmarks():
    from .benchmark_queries import comparable_groups

    db = get_db()
    clauses, params = [], []
    benchmark_name = request.args.get("benchmark")
    version = request.args.get("version")
    model = request.args.get("model")
    current_only = request.args.get("current_only", "false").casefold() in {"1", "true", "yes"}
    if benchmark_name:
        clauses.append("b.name=?")
        params.append(benchmark_name)
    if version:
        clauses.append("b.version=?")
        params.append(version)
    if current_only:
        clauses.append("b.is_current=1")
    model_ids = []
    for value in [model] if model else []:
        found = db.execute("SELECT id FROM models WHERE canonical_slug=? OR lower(canonical_name)=lower(?)", (value, value)).fetchone()
        if not found:
            return jsonify({"error": {"code": "unknown_model", "message": f"Unknown canonical model: {value}"}}), 400
        model_ids.append(found[0])
    compare_values = [part.strip() for part in request.args.get("compare", "").split(",") if part.strip()]
    for value in compare_values:
        found = db.execute("SELECT id FROM models WHERE canonical_slug=? OR lower(canonical_name)=lower(?)", (value, value)).fetchone()
        if not found:
            return jsonify({"error": {"code": "unknown_model", "message": f"Unknown canonical model: {value}"}}), 400
        model_ids.append(found[0])
    model_ids = list(dict.fromkeys(model_ids))
    if compare_values and len(model_ids) < 2:
        return jsonify({"error": {"code": "comparison_requires_two_models", "message": "Pass at least two distinct model slugs in compare."}}), 400
    data = []
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    for row in db.execute(f"SELECT b.*,s.name source_name,s.url source_url FROM benchmarks b LEFT JOIN sources s ON s.id=b.source_id {where} ORDER BY b.name,b.version", params):
        item = dict(row)
        item["slug"] = slugify(f"{row['name']}-{row['version']}")
        item["source"] = _source(item)
        item.pop("source_id", None)
        item.pop("source_name", None)
        item.pop("source_url", None)
        result_clauses, result_params = ["br.benchmark_id=?"], [row["id"]]
        if current_only:
            result_clauses.append("b.is_current=1")
        if benchmark_name:
            result_clauses.append("b.name=?")
            result_params.append(benchmark_name)
        if version:
            result_clauses.append("b.version=?")
            result_params.append(version)
        if model_ids:
            result_clauses.append(f"br.model_id IN ({','.join('?' for _ in model_ids)})")
            result_params.extend(model_ids)
        item["results"] = [dict(x) for x in db.execute(f"""SELECT br.model_id,b.id benchmark_id,b.name benchmark,b.version,
          m.canonical_name model,m.canonical_slug model_slug,
          br.model_version,br.score,br.metric,br.task_subset,br.harness_name,br.harness_version,
          br.scaffold,br.reasoning_setting,br.tool_policy,br.network_policy,br.step_budget,
          br.token_budget,br.time_budget_seconds,br.attempts_per_task,br.grader_version,
          br.confidence_interval,br.evaluated_at,br.confidence,s.name source_name,s.url source_url,
          b.is_current,b.published_at,b.last_verified_at
          FROM benchmark_results br JOIN models m ON m.id=br.model_id JOIN benchmarks b ON b.id=br.benchmark_id
          LEFT JOIN sources s ON s.id=br.source_id WHERE {' AND '.join(result_clauses)}
          ORDER BY br.metric,br.task_subset,br.harness_name,br.harness_version,br.scaffold,
            br.reasoning_setting,br.tool_policy,br.network_policy,br.attempts_per_task,
            br.grader_version,br.score DESC""", result_params)]
        item["comparable_groups"] = comparable_groups(item["results"]) if compare_values else []
        data.append(item)
    return _paged_envelope(data, compared_models=compare_values,
                           caveat="Scores compare only within the same benchmark version, metric, task and published run configuration. Route prices are provider-specific.")


@public.get("/api/v1/compatibility")
def api_compatibility():
    harness = _harness(request.args.get("harness"))
    if not harness:
        return jsonify({"error": {"code": "invalid_harness", "message": "A known harness id, name, or slug is required."}}), 400
    filters_in = _unpaged_args()
    filters_in.update(limit=100000, offset=0)
    routes, filters = filtered_routes(filters_in)
    data = [_route_json(row, row.get("_compatibility") or compatibility_for(
        get_db(), harness["id"], row["offering_id"], filters.get("mcp") == "1")) for row in routes]
    return _paged_envelope(data, harness={"id": harness["id"], "name": harness["name"], "slug": slugify(harness["name"])}, warnings=filters.get("filter_errors", []))


@public.get("/api/v1/search")
def api_search():
    filters_in = _unpaged_args()
    filters_in.update(limit=100000, offset=0)
    routes, filters = filtered_routes(filters_in)
    return _paged_envelope([_route_json(row, row.get("_compatibility")) for row in routes], filters=filters, warnings=filters.get("filter_errors", []))


@public.get("/robots.txt")
def robots():
    root = public_origin()
    policy = f"""# Public factual pages are available to search and answer engines.
User-agent: Googlebot
User-agent: Bingbot
User-agent: OAI-SearchBot
User-agent: PerplexityBot
User-agent: Claude-SearchBot
User-agent: Applebot
User-agent: ChatGPT-User
User-agent: Claude-User
User-agent: Perplexity-User
Allow: /
Disallow: /internal/
Disallow: /analytics/
Disallow: /*?

User-agent: GPTBot
Disallow: /

User-agent: ClaudeBot
Disallow: /

User-agent: Applebot-Extended
Disallow: /

User-agent: *
Allow: /
Disallow: /internal/
Disallow: /analytics/
Disallow: /*?

Sitemap: {root}/sitemap.xml
"""
    return Response(policy, mimetype="text/plain")


@public.get("/llms.txt")
def llms_txt():
    root = public_origin()
    body = f"""# UseThisModel

UseThisModel is a continuously updated, source-backed catalog of AI models,
exact provider routes, pricing, plans, offers, harness compatibility, releases,
benchmarks, use cases, and workflows.

Canonical URL: {root}/

## Key resources
- Models: {root}/models
- Providers: {root}/providers
- Harnesses: {root}/harnesses
- Compatibility: {root}/compatibility
- Current offers: {root}/deals
- New releases: {root}/releases
- Benchmarks: {root}/benchmarks
- Use cases: {root}/use-cases
- Workflows: {root}/workflows
- Public API documentation: {root}/api
- OpenAPI: {root}/api/v1/openapi.json
- Sitemap: {root}/sitemap.xml

## Data semantics
Facts retain their source links, caveats, and last-verified timestamps. Unknown
values remain unknown rather than being inferred. Prices identify their unit and
currency; model identity is separate from an exact provider route.
"""
    return _conditional_text(body)


def _conditional_text(body, mimetype="text/plain"):
    response = make_response(body)
    response.mimetype = mimetype
    response.set_etag(sha256(body.encode("utf-8")).hexdigest(), weak=False)
    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=60"
    return response.make_conditional(request)


@public.get("/llms-full.txt")
def llms_full_txt():
    db = get_db()
    root = public_origin()
    lines = ["# UseThisModel — current catalog overview", "",
             "Source-backed catalog snapshot. Raw source modality and route details are available in the API.",
             "Unknown facts remain unknown; pricing and access semantics are route-specific.", "",
             "## Models with the broadest current route coverage"]
    models = db.execute("""SELECT m.canonical_name,m.canonical_slug,m.vendor,m.modality,m.released_at,
      m.release_date_kind,COUNT(o.id) routes FROM models m JOIN provider_offerings o ON o.model_id=m.id
      WHERE m.status!='DEPRECATED' GROUP BY m.id ORDER BY routes DESC,m.released_at DESC,m.canonical_name LIMIT 100""").fetchall()
    for row in models:
        lines.append(f"- [{row['canonical_name']}]({root}/models/{row['canonical_slug']}) — {row['vendor']}; {modality_category(row['modality'], row['canonical_name'])}; {row['routes']} routes; release {row['released_at'] or 'unknown'} ({row['release_date_kind']}).")
    lines.extend(["", "## Providers"])
    for row in db.execute("SELECT name,website_url FROM providers WHERE canonical_provider_id IS NULL ORDER BY name LIMIT 50"):
        lines.append(f"- [{row['name']}]({row['website_url'] or root + '/providers'})")
    lines.extend(["", "## Harnesses"])
    for row in db.execute("SELECT name,website_url FROM harnesses ORDER BY name"):
        lines.append(f"- [{row['name']}]({row['website_url'] or root + '/harnesses'})")
    lines.extend(["", "## Plans"])
    for row in db.execute("SELECT pl.name,p.name provider_name,pl.plan_type,pl.monthly_price,pl.currency,s.url source_url FROM plans pl JOIN providers p ON p.id=pl.provider_id LEFT JOIN sources s ON s.id=pl.source_id WHERE pl.status IN ('ACTIVE','LIMITED','WAITLIST') ORDER BY p.name,pl.name LIMIT 40"):
        price = f"{row['currency'] or 'USD'} {row['monthly_price']}/month" if row['monthly_price'] is not None else "price unverified"
        lines.append(f"- {row['name']} ({row['provider_name']}; {row['plan_type']}; {price}) — {row['source_url'] or root + '/plans'}")
    lines.extend(["", "## Current offers"])
    for row in offer_rows(db)[:50]:
        lines.append(f"- {row['title']} ({row['provider_name']}; {row['offer_type']}; verified {row['last_verified_at'] or 'unknown'}; ends {row['ends_at'] or 'not published'}) — {row['terms_url'] or root + '/deals'}")
    lines.extend(["", "## Workflows"])
    for row in db.execute("SELECT slug,name,description FROM workflows ORDER BY name"):
        lines.append(f"- [{row['name']}]({root}/workflows/{row['slug']}) — {row['description'] or 'Documented tool workflow.'}")
    lines.extend(["", "## Machine interfaces", f"- API docs: {root}/api", f"- OpenAPI: {root}/api/v1/openapi.json", f"- MCP: {root}/mcp-info"])
    return _conditional_text("\n".join(lines) + "\n")


@public.get("/sitemap.xml")
def sitemap():
    root = public_origin()
    groups = ["core", "models", "providers", "harnesses", "use-cases", "workflows"]
    body = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><sitemapindex xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">" + "".join(
        f"<sitemap><loc>{root}/sitemaps/{group}.xml</loc></sitemap>" for group in groups) + "</sitemapindex>"
    return _conditional_text(body, "application/xml")


def _urlset(paths):
    root = public_origin()
    items = []
    seen = set()
    for item in paths:
        path, lastmod = item if isinstance(item, tuple) else (item, None)
        if path in seen:
            continue
        seen.add(path)
        lastmod_xml = f"<lastmod>{escape(str(lastmod)[:10])}</lastmod>" if lastmod else ""
        items.append(f"<url><loc>{escape(root + path)}</loc>{lastmod_xml}</url>")
    body = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">" + "".join(items) + "</urlset>"
    return _conditional_text(body, "application/xml")


@public.get("/sitemaps/<group>.xml")
def sitemap_group(group):
    db = get_db()
    groups = {
        "core": lambda: ["/", "/models", "/providers", "/harnesses", "/workflows", "/benchmarks",
                         "/use-cases", "/deals", "/releases", "/rankings", "/plans", "/api", "/mcp-info"] +
                        ["/benchmarks/" + slugify(f"{row[0]}-{row[1]}") for row in db.execute("SELECT name,version FROM benchmarks")],
        "models": lambda: [("/models/" + row[0], row[1]) for row in db.execute("""SELECT m.canonical_slug,
                            (SELECT MAX(d.observed_at) FROM selected_facts sf JOIN data_observations d ON d.id=sf.observation_id
                             WHERE sf.entity='model:'||m.id) lastmod FROM models m
                            WHERE m.canonical_slug IS NOT NULL AND m.status!='DEPRECATED'
                            AND EXISTS(SELECT 1 FROM provider_offerings o WHERE o.model_id=m.id)""")],
        "providers": lambda: ["/providers/" + slugify(row[0]) for row in db.execute("SELECT name FROM providers WHERE canonical_provider_id IS NULL")],
        "harnesses": lambda: ["/harnesses/" + slugify(row[0]) for row in db.execute("SELECT name FROM harnesses")],
        "use-cases": lambda: ["/use-cases/free-tool-calling", "/use-cases/3d-generation"] + ["/use-cases/" + row[0] for row in db.execute("SELECT slug FROM use_cases WHERE slug!='3d'")],
        "workflows": lambda: ["/workflows/" + row[0] for row in db.execute("SELECT slug FROM workflows")],
    }
    if group not in groups:
        abort(404)
    return _urlset(groups[group]())


def _feed(title, path, entries):
    root = public_origin()
    timestamps = [str(entry[2]) for entry in entries if entry[2]]
    updated = max(timestamps, default="1970-01-01")
    if "T" not in updated:
        updated += "T00:00:00Z"
    def atom_time(value):
        value = str(value or datetime.now(timezone.utc).isoformat())
        if "T" not in value:
            value += "T00:00:00Z"
        return value.replace("+00:00", "Z")
    items = "".join(f"<entry><id>{escape(root + url)}</id><title>{escape(str(name))}</title><link href=\"{escape(root + url)}\"/><updated>{escape(atom_time(when))}</updated><summary>{escape(str(summary))}</summary></entry>" for name, url, when, summary in entries)
    body = f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><feed xmlns=\"http://www.w3.org/2005/Atom\"><id>{root}{path}</id><title>{title}</title><updated>{updated}</updated><link href=\"{root}{path}\" rel=\"self\"/>{items}</feed>"
    return _conditional_text(body, "application/atom+xml")


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


def _offer_entries(status):
    records = offer_rows(get_db(), include_expired=True)
    selected = [row for row in records if row["status"] == status][:50]
    return [(row["title"], "/deals", row["last_verified_at"] or row["ends_at"] or row["starts_at"],
             f"{row['provider_name']} · {row['offer_type']} · {row['status']}; expires {row['ends_at'] or 'not published'}.")
            for row in selected]


@public.get("/feeds/deals.atom")
def deal_feed():
    return _feed("UseThisModel new and current deals", "/feeds/deals.atom", _offer_entries("ACTIVE"))


@public.get("/feeds/expired-deals.atom")
def expired_deal_feed():
    return _feed("UseThisModel expired deals", "/feeds/expired-deals.atom", _offer_entries("EXPIRED"))


@public.get("/feeds/changes.json")
def changes_json_feed():
    root = public_origin()
    def json_time(value):
        value = str(value or datetime.now(timezone.utc).isoformat())
        return (value + "T00:00:00Z") if "T" not in value else value.replace("+00:00", "Z")
    releases = [dict(row) for row in get_db().execute(
        "SELECT canonical_name,canonical_slug,released_at,modality FROM models WHERE released_at IS NOT NULL ORDER BY released_at DESC LIMIT 20")]
    items = [{"id": root + "/models/" + row["canonical_slug"], "url": root + "/models/" + row["canonical_slug"],
              "title": row["canonical_name"], "date_published": json_time(row["released_at"]),
              "content_text": f"New {row['modality']} model release."} for row in releases]
    for row in _offer_entries("ACTIVE")[:20]:
        items.append({"id": root + row[1] + "#" + slugify(row[0]), "url": root + row[1],
                      "title": row[0], "date_modified": json_time(row[2]), "content_text": row[3]})
    response = jsonify({"version": "https://jsonfeed.org/version/1.1", "title": "UseThisModel catalog changes",
                        "home_page_url": root, "feed_url": root + "/feeds/changes.json", "items": items})
    response.set_etag(sha256(response.get_data()).hexdigest(), weak=False)
    response.headers.setdefault("Cache-Control", "public, max-age=60, stale-while-revalidate=30")
    return response.make_conditional(request)

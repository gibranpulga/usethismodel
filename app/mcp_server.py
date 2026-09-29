"""Read-only MCP facade over the existing UseThisModel SQLite catalogue."""

from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Annotated, Any

from a2wsgi import WSGIMiddleware
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.applications import Starlette
from starlette.routing import Mount

from .db import get_db as _get_db
from .domain import compatibility_for
from .public import slugify
from .query import offer_rows, plan_rows, route_rows, source_rows

SERVER_NAME = "usethismodel"
SERVER_VERSION = "1.0.0"
MAX_LIMIT = 50
COMPATIBLE = {"COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION", "PARTIAL"}
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

server = MCPServer(
    SERVER_NAME,
    title="UseThisModel",
    version=SERVER_VERSION,
    website_url="https://usethismodel.codefiction.net/mcp-info",
    instructions=(
        "Read-only, source-backed AI model and provider-route catalogue. Prices and capabilities "
        "are route-specific; unknown facts remain unknown. Prefer compatibility tools for harness "
        "or MCP workflow questions, and report last_verified_at plus source URLs."
    ),
)

_bound_app = None


def bind_app(app):
    global _bound_app
    _bound_app = app
    return app


def _app():
    if _bound_app is None:
        from . import create_app

        bind_app(create_app())
    return _bound_app


def get_db():
    """Return this tool call's connection with SQLite writes disabled."""
    db = _get_db()
    db.execute("PRAGMA query_only = ON")
    return db


def _page(limit: int, cursor: str | None) -> tuple[int, int]:
    if limit < 1 or limit > MAX_LIMIT:
        raise ToolError(f"limit must be between 1 and {MAX_LIMIT}")
    if cursor in (None, ""):
        return limit, 0
    try:
        offset = int(cursor)
    except (TypeError, ValueError) as exc:
        raise ToolError("cursor must be a non-negative integer returned by a previous call") from exc
    if offset < 0 or offset > 10_000:
        raise ToolError("cursor is outside the supported range 0..10000")
    return limit, offset


def _paged(items: list, limit: int, offset: int, **meta) -> dict[str, Any]:
    window = items[offset : offset + limit + 1]
    more = len(window) > limit
    return {
        "items": window[:limit],
        "page": {"limit": limit, "cursor": str(offset),
                 "next_cursor": str(offset + limit) if more else None},
        **meta,
    }


def _harness(db, value: str | None):
    if not value:
        return None
    wanted = value.lower()
    wanted = {"hermes": "hermes-agent", "codex": "codex-cli"}.get(wanted, wanted)
    return next((row for row in db.execute("SELECT * FROM harnesses")
                 if str(row["id"]) == wanted or row["name"].lower() == wanted
                 or slugify(row["name"]) == wanted), None)


def _workflow(db, value: str | None):
    if not value:
        return None
    return db.execute("SELECT * FROM workflows WHERE lower(slug)=lower(?) OR lower(name)=lower(?)",
                      (value, value)).fetchone()


def _model(db, value: str):
    return db.execute(
        """SELECT m.*,COALESCE(l.name,m.vendor) lab_name FROM models m
           LEFT JOIN labs l ON l.id=m.lab_id
           WHERE lower(m.canonical_slug)=lower(?) OR lower(m.canonical_name)=lower(?)""",
        (value, value),
    ).fetchone()


def _route_source(row) -> list[dict[str, Any]]:
    if not row.get("route_source_url"):
        return []
    return [{"name": row.get("route_source_name"), "url": row["route_source_url"]}]


def _route_json(row, compatibility=None) -> dict[str, Any]:
    result = {
        "route_id": row["offering_id"],
        "api_model_id": row["api_model_id"],
        "canonical_model": {"name": row["canonical_name"], "slug": row["canonical_slug"],
                            "type": row["modality"], "open_weights": bool(row["open_weights"])},
        "provider": row["provider_name"],
        "price_usd_per_million_tokens": {"input": row["input_price"],
                                           "output": row["output_price"],
                                           "cache_read": row["cache_read_price"]},
        "capabilities": {"tools": row["tool_support"],
                         "structured_output": row["structured_output_support"],
                         "reasoning": "YES" if row["reasoning"] else "UNKNOWN",
                         "vision": "YES" if row["vision"] else "UNKNOWN"},
        "limits": {"context_tokens": row["context_limit"],
                   "max_output_tokens": row["max_output_tokens"]},
        "free_status": row["free_status"],
        "active_deal": bool(row["active_deal"]),
        "last_verified_at": row["last_verified_at"] or row["fetched_at"],
        "sources": _route_source(row),
    }
    if row["media_price"] is not None:
        result["media_price"] = {"amount": row["media_price"], "unit": row["media_price_unit"],
                                 "type": row["media_price_type"], "currency": "USD"}
    if compatibility is not None:
        result["compatibility"] = compatibility
        source = compatibility.get("source") if isinstance(compatibility, dict) else None
        if source and source.get("url") and source not in result["sources"]:
            result["sources"].append(source)
    return result


def _routes(db, filters: dict[str, Any], harness_name: str | None = None,
            workflow_name: str | None = None, require_mcp: bool = False) -> list[dict[str, Any]]:
    harness = _harness(db, harness_name)
    if harness_name and not harness:
        raise ToolError(f"Unknown harness: {harness_name}")
    workflow = _workflow(db, workflow_name)
    if workflow_name and not workflow:
        raise ToolError(f"Unknown workflow: {workflow_name}")
    candidates = route_rows(db, {**filters, "limit": 10_000, "offset": 0})
    if not harness and not workflow:
        return [_route_json(row) for row in candidates]
    harnesses = [harness] if harness else list(db.execute("SELECT * FROM harnesses WHERE supports_mcp=1"))
    found = []
    for row in candidates:
        matches = []
        for candidate_harness in harnesses:
            result = compatibility_for(db, candidate_harness["id"], row["offering_id"],
                                       require_mcp or workflow is not None,
                                       workflow["id"] if workflow else None)
            if result["status"] in COMPATIBLE:
                matches.append((candidate_harness, result))
        if matches:
            selected_harness, match = matches[0]
            match = {"harness": selected_harness["name"], **match}
            found.append(_route_json(row, match))
    return found


def _filters(query=None, provider=None, tools=None, free=None, open_weights=None,
             min_context=None, max_input_price=None, max_output_price=None,
             model_id=None, route_id=None, model_type=None, sort=None):
    values = {"q": query, "provider": provider, "context": min_context,
              "input_max": max_input_price, "output_max": max_output_price,
              "model_id": model_id, "offering_id": route_id, "type": model_type,
              "sort": sort}
    if tools is not None:
        values["tools"] = "1" if tools else "0"
    if free is not None:
        values["free"] = "1" if free else "0"
    if open_weights is not None:
        values["open_weights"] = "1" if open_weights else "0"
    return {key: value for key, value in values.items() if value not in (None, "")}


Limit = Annotated[int, Field(ge=1, le=MAX_LIMIT, description="Maximum results (1-50).")]
PositiveInt = Annotated[int, Field(ge=0)]
Price = Annotated[float, Field(ge=0)]


@server.tool(title="Search models", annotations=READ_ONLY, structured_output=True)
def search_models(query: str | None = None, tools: bool | None = None,
                  free: bool | None = None, open_weights: bool | None = None,
                  model_type: str | None = None, limit: Limit = 10,
                  cursor: str | None = None) -> dict[str, Any]:
    """Search canonical models, returning compact route evidence and pagination."""
    limit, offset = _page(limit, cursor)
    with _app().app_context():
        db = get_db()
        routes = _routes(db, _filters(query=query, tools=tools, free=free,
                                      open_weights=open_weights, model_type=model_type))
        grouped = {}
        for route in routes:
            slug = route["canonical_model"]["slug"]
            item = grouped.setdefault(slug, {**route["canonical_model"], "routes": []})
            if len(item["routes"]) < 3:
                item["routes"].append(route)
        return _paged(list(grouped.values()), limit, offset)


@server.tool(title="Get model", annotations=READ_ONLY, structured_output=True)
def get_model(model: str, route_limit: Annotated[int, Field(ge=1, le=20)] = 10) -> dict[str, Any]:
    """Get one exact canonical model by name or slug, including routes and sources."""
    with _app().app_context():
        db = get_db()
        found = _model(db, model)
        if not found:
            raise ToolError(f"Unknown model: {model}")
        routes = _routes(db, _filters(model_id=found["id"]))[:route_limit]
        return {"model": {"id": found["id"], "name": found["canonical_name"],
                          "slug": found["canonical_slug"], "lab": found["lab_name"],
                          "type": found["modality"], "release_date": found["released_at"],
                          "open_weights": bool(found["open_weights"])},
                "routes": routes, "sources": source_rows(db, model_id=found["id"])}


@server.tool(title="Search provider routes", annotations=READ_ONLY, structured_output=True)
def search_provider_routes(query: str | None = None, provider: str | None = None,
                           tools: bool | None = None, free: bool | None = None,
                           min_context: PositiveInt | None = None,
                           max_input_price: Price | None = None,
                           max_output_price: Price | None = None,
                           harness: str | None = None, limit: Limit = 10,
                           cursor: str | None = None) -> dict[str, Any]:
    """Find exact provider routes by model, provider, price, context, tools, or harness."""
    limit, offset = _page(limit, cursor)
    with _app().app_context():
        routes = _routes(get_db(), _filters(query=query, provider=provider, tools=tools,
                                            free=free, min_context=min_context,
                                            max_input_price=max_input_price,
                                            max_output_price=max_output_price), harness)
        return _paged(routes, limit, offset)


@server.tool(title="Compare models", annotations=READ_ONLY, structured_output=True)
def compare_models(models: Annotated[list[str], Field(min_length=2, max_length=6)]) -> dict[str, Any]:
    """Compare two to six canonical models and their cheapest recorded routes."""
    with _app().app_context():
        db = get_db()
        items, unknown = [], []
        for value in models:
            found = _model(db, value)
            if not found:
                unknown.append(value)
                continue
            routes = _routes(db, _filters(model_id=found["id"], sort="price"))
            items.append({"model": {"name": found["canonical_name"], "slug": found["canonical_slug"],
                                     "type": found["modality"], "release_date": found["released_at"]},
                          "routes": routes[:5]})
        return {"items": items, "unknown_models": unknown,
                "comparison_note": "Routes are ordered by recorded input price, then output price; this is not a quality ranking."}


@server.tool(title="Compare routes", annotations=READ_ONLY, structured_output=True)
def compare_routes(route_ids: Annotated[list[int], Field(min_length=2, max_length=10)]) -> dict[str, Any]:
    """Compare exact route IDs with price, limits, capabilities, freshness, and sources."""
    with _app().app_context():
        db = get_db()
        items, unknown = [], []
        for route_id in route_ids:
            rows = _routes(db, _filters(route_id=route_id))
            (items if rows else unknown).append(rows[0] if rows else route_id)
        return {"items": items, "unknown_route_ids": unknown}


@server.tool(title="Find cheapest routes", annotations=READ_ONLY, structured_output=True)
def find_cheapest_routes(harness: str | None = None, tools: bool = False,
                         min_context: PositiveInt | None = None,
                         input_tokens: PositiveInt = 1_000_000,
                         output_tokens: PositiveInt = 1_000_000,
                         limit: Limit = 10, cursor: str | None = None) -> dict[str, Any]:
    """Rank routes by calculated token cost, optionally requiring harness compatibility."""
    limit, offset = _page(limit, cursor)
    with _app().app_context():
        routes = _routes(get_db(), _filters(tools=tools, min_context=min_context), harness)
        priced = []
        for route in routes:
            price = route["price_usd_per_million_tokens"]
            if price["input"] is None or price["output"] is None:
                continue
            cost = price["input"] * input_tokens / 1_000_000 + price["output"] * output_tokens / 1_000_000
            priced.append({**route, "calculated_cost_usd": round(cost, 8)})
        priced.sort(key=lambda row: (row["calculated_cost_usd"], row["canonical_model"]["name"], row["provider"]))
        return _paged(priced, limit, offset, cost_basis={"input_tokens": input_tokens,
                                                        "output_tokens": output_tokens})


@server.tool(title="Find free models", annotations=READ_ONLY, structured_output=True)
def find_free_models(tools: bool = False, harness: str | None = None,
                     limit: Limit = 10, cursor: str | None = None) -> dict[str, Any]:
    """Find routes whose current input and output token prices are both exactly zero."""
    limit, offset = _page(limit, cursor)
    with _app().app_context():
        return _paged(_routes(get_db(), _filters(free=True, tools=tools), harness), limit, offset,
                      definition="Free means this exact route records both input and output as USD 0; terms and rate limits may apply.")


@server.tool(title="Find tool-capable models", annotations=READ_ONLY, structured_output=True)
def find_tool_capable_models(harness: str | None = None,
                             min_context: PositiveInt | None = None,
                             limit: Limit = 10, cursor: str | None = None) -> dict[str, Any]:
    """Find provider routes with explicit tool-calling support."""
    limit, offset = _page(limit, cursor)
    with _app().app_context():
        return _paged(_routes(get_db(), _filters(tools=True, min_context=min_context), harness), limit, offset)


@server.tool(title="Find models for harness", annotations=READ_ONLY, structured_output=True)
def find_models_for_harness(harness: str, tools: bool = False, require_mcp: bool = False,
                            min_context: PositiveInt | None = None,
                            limit: Limit = 10, cursor: str | None = None) -> dict[str, Any]:
    """Find routes compatible with Hermes, Codex CLI, OpenCode, Pi, or another known harness."""
    limit, offset = _page(limit, cursor)
    with _app().app_context():
        routes = _routes(get_db(), _filters(tools=tools, min_context=min_context),
                         harness, require_mcp=require_mcp)
        return _paged(routes, limit, offset, harness=harness, mcp_required=require_mcp)


@server.tool(title="Find models for workflow", annotations=READ_ONLY, structured_output=True)
def find_models_for_workflow(workflow: str, harness: str | None = None,
                             min_context: PositiveInt | None = None,
                             limit: Limit = 10, cursor: str | None = None) -> dict[str, Any]:
    """Find tool-capable routes for a recorded MCP workflow such as Unreal Engine MCP."""
    limit, offset = _page(limit, cursor)
    with _app().app_context():
        routes = _routes(get_db(), _filters(tools=True, min_context=min_context),
                         harness, workflow, require_mcp=True)
        return _paged(routes, limit, offset, workflow=workflow, harness=harness)


@server.tool(title="Get compatibility", annotations=READ_ONLY, structured_output=True)
def get_compatibility(harness: str, route_id: int | None = None,
                      model: str | None = None, workflow: str | None = None) -> dict[str, Any]:
    """Explain compatibility checks for one route or every route of one exact model."""
    if route_id is None and not model:
        raise ToolError("Provide route_id or model")
    with _app().app_context():
        db = get_db()
        filters = _filters(route_id=route_id)
        if model:
            found = _model(db, model)
            if not found:
                raise ToolError(f"Unknown model: {model}")
            filters["model_id"] = found["id"]
        routes = _routes(db, filters, harness, workflow, require_mcp=workflow is not None)
        return {"items": routes, "harness": harness, "workflow": workflow,
                "note": "Only compatible, compatible-with-configuration, or partial routes are returned."}


@server.tool(title="Get current deals", annotations=READ_ONLY, structured_output=True)
def get_current_deals(provider: str | None = None, limit: Limit = 10,
                      cursor: str | None = None) -> dict[str, Any]:
    """List currently active, source-backed offers with verification dates."""
    limit, offset = _page(limit, cursor)
    with _app().app_context():
        deals = offer_rows(get_db())
        if provider:
            deals = [deal for deal in deals if deal["provider_name"].lower() == provider.lower()]
        compact = [{**{key: deal.get(key) for key in ("id", "title", "description", "provider_name",
                    "canonical_name", "api_model_id", "offer_type", "starts_at", "ends_at",
                    "terms_url", "current_input_price", "current_output_price", "original_input_price",
                    "original_output_price", "discount_percent", "last_verified_at", "verification_note")},
                    "sources": ([{"name": "Offer terms", "url": deal["terms_url"]}]
                                if deal.get("terms_url") else [])}
                   for deal in deals]
        return _paged(compact, limit, offset)


@server.tool(title="Get new releases", annotations=READ_ONLY, structured_output=True)
def get_new_releases(days: Annotated[int, Field(ge=1, le=365)] = 7,
                     limit: Limit = 10, cursor: str | None = None) -> dict[str, Any]:
    """List canonical models released within a bounded number of days."""
    limit, offset = _page(limit, cursor)
    since = (date.today() - timedelta(days=days)).isoformat()
    with _app().app_context():
        db = get_db()
        rows = [dict(row) for row in db.execute(
            """SELECT m.id,m.canonical_name name,m.canonical_slug slug,m.modality type,
               m.released_at release_date,m.release_date_kind,m.status,
               MAX(COALESCE(o.last_verified_at,o.fetched_at)) last_verified_at
               FROM models m LEFT JOIN provider_offerings o ON o.model_id=m.id
               WHERE m.released_at>=? GROUP BY m.id ORDER BY m.released_at DESC,m.canonical_name""", (since,))]
        for row in rows:
            row["sources"] = source_rows(db, model_id=row["id"])
        return _paged(rows, limit, offset, since=since, days=days)


@server.tool(title="Get benchmarks", annotations=READ_ONLY, structured_output=True)
def get_benchmarks(model: str | None = None, current_only: bool = False,
                   limit: Limit = 10, cursor: str | None = None) -> dict[str, Any]:
    """Get benchmark metadata and measurements without turning scores into a universal ranking."""
    limit, offset = _page(limit, cursor)
    with _app().app_context():
        db = get_db()
        params, clauses = [], []
        if current_only:
            clauses.append("b.is_current=1")
        if model:
            found = _model(db, model)
            if not found:
                raise ToolError(f"Unknown model: {model}")
            clauses.append("br.model_id=?")
            params.append(found["id"])
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = [dict(row) for row in db.execute(f"""SELECT b.id,b.name,b.version,b.category,b.description,
          b.methodology_url,b.published_at,b.last_verified_at,m.canonical_name model,m.canonical_slug model_slug,
          br.score,br.metric,br.harness_name,br.scaffold,br.reasoning_setting,br.evaluated_at,br.confidence,
          s.name source_name,s.url source_url FROM benchmarks b LEFT JOIN benchmark_results br ON br.benchmark_id=b.id
          LEFT JOIN models m ON m.id=br.model_id LEFT JOIN sources s ON s.id=COALESCE(br.source_id,b.source_id)
          {where} ORDER BY b.name,b.version,br.score DESC""", params)]
        for row in rows:
            row["sources"] = ([{"name": row.pop("source_name"), "url": row.pop("source_url")}]
                              if row.get("source_url") else [])
        return _paged(rows, limit, offset,
                      caveat="Scores are benchmark-version and harness/scaffold specific; compare like with like.")


@server.tool(title="Calculate route cost", annotations=READ_ONLY, structured_output=True)
def calculate_cost(route_id: int, input_tokens: PositiveInt = 0,
                   output_tokens: PositiveInt = 0, cache_read_tokens: PositiveInt = 0) -> dict[str, Any]:
    """Calculate a token cost from one route's current recorded prices."""
    with _app().app_context():
        routes = _routes(get_db(), _filters(route_id=route_id))
        if not routes:
            raise ToolError(f"Unknown route_id: {route_id}")
        route = routes[0]
        price = route["price_usd_per_million_tokens"]
        missing = [name for name, tokens in (("input", input_tokens), ("output", output_tokens),
                   ("cache_read", cache_read_tokens)) if tokens and price[name] is None]
        if missing:
            raise ToolError("Price is unknown for requested token classes: " + ", ".join(missing))
        cost = sum((price[name] or 0) * tokens / 1_000_000 for name, tokens in
                   (("input", input_tokens), ("output", output_tokens), ("cache_read", cache_read_tokens)))
        return {"route": route, "usage": {"input_tokens": input_tokens,
                "output_tokens": output_tokens, "cache_read_tokens": cache_read_tokens},
                "estimated_cost_usd": round(cost, 8),
                "caveat": "Estimate excludes taxes, minimums, tiering, provider routing, and unrecorded fees."}


@server.tool(title="Get plan options", annotations=READ_ONLY, structured_output=True)
def get_plan_options(provider: str | None = None, harness: str | None = None,
                     coding: bool = False, api_access: bool = False, free: bool = False,
                     max_monthly_price: Price | None = None,
                     limit: Limit = 10, cursor: str | None = None) -> dict[str, Any]:
    """Find subscriptions, free plans, PAYG, and enterprise options without inventing token equivalents."""
    limit, offset = _page(limit, cursor)
    filters = {"provider": provider, "harness": harness, "max_price": max_monthly_price}
    if coding:
        filters["coding"] = "1"
    if api_access:
        filters["api"] = "1"
    if free:
        filters["free"] = "1"
    with _app().app_context():
        plans = plan_rows(get_db(), {k: v for k, v in filters.items() if v not in (None, "")})
        keep = ("id", "provider_name", "name", "description", "plan_type", "monthly_price",
                "annual_price", "currency", "price_note", "models_included", "api_access",
                "coding_agent_access", "quota_description", "published_limit", "fair_use",
                "status", "verified_at", "source_url", "compatibility")
        return _paged([{key: plan.get(key) for key in keep} for plan in plans], limit, offset)


def _resource_json(value) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


@server.resource("utm://models", title="Canonical models", mime_type="application/json")
def models_resource() -> str:
    with _app().app_context():
        return _resource_json([dict(row) for row in get_db().execute(
            "SELECT canonical_name name,canonical_slug slug,modality type,released_at release_date,status FROM models ORDER BY canonical_name")])


@server.resource("utm://providers", title="Providers", mime_type="application/json")
def providers_resource() -> str:
    with _app().app_context():
        return _resource_json([dict(row) for row in get_db().execute(
            "SELECT id,name,website_url FROM providers WHERE canonical_provider_id IS NULL ORDER BY name")])


@server.resource("utm://harnesses", title="Harnesses", mime_type="application/json")
def harnesses_resource() -> str:
    with _app().app_context():
        return _resource_json([dict(row) for row in get_db().execute(
            "SELECT id,name,interfaces,supports_mcp,version_verified_at last_verified_at FROM harnesses ORDER BY name")])


@server.resource("utm://offers", title="Current offers", mime_type="application/json")
def offers_resource() -> str:
    return _resource_json(get_current_deals(limit=50)["items"])


@server.resource("utm://benchmark-metadata", title="Benchmark metadata", mime_type="application/json")
def benchmarks_resource() -> str:
    with _app().app_context():
        return _resource_json([dict(row) for row in get_db().execute(
            "SELECT name,version,category,description,methodology_url,last_verified_at FROM benchmarks ORDER BY name,version")])


class RateLimitMiddleware:
    """Small per-process fixed-window guard for the public MCP transport."""

    def __init__(self, app, requests_per_minute: int):
        self.app = app
        self.limit = max(1, requests_per_minute)
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return
        client = scope.get("client") or ("unknown", 0)
        forwarded = next((v.decode("latin1").rsplit(",", 1)[-1].strip() for k, v in scope.get("headers", [])
                          if k.lower() == b"x-forwarded-for"), None)
        key = forwarded or client[0]
        now = time.monotonic()
        with self.lock:
            bucket = self.hits[key]
            while bucket and bucket[0] <= now - 60:
                bucket.popleft()
            allowed = len(bucket) < self.limit
            if allowed:
                bucket.append(now)
        if not allowed:
            body = b'{"error":"rate_limit_exceeded","retry_after_seconds":60}'
            await send({"type": "http.response.start", "status": 429,
                        "headers": [(b"content-type", b"application/json"), (b"retry-after", b"60")]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


class AggregateUsageMiddleware:
    """Count MCP HTTP requests without reading or retaining request bodies."""

    def __init__(self, app, flask_app):
        self.app = app
        self.flask_app = flask_app

    async def __call__(self, scope, receive, send):
        await self.app(scope, receive, send)
        if scope["type"] == "http" and scope.get("path", "").startswith("/mcp"):
            try:
                from .analytics import record
                from .db import get_db as writable_db
                with self.flask_app.app_context():
                    record(writable_db(), "mcp_request", scope.get("method", "UNKNOWN"))
            except Exception:
                self.flask_app.logger.exception("MCP aggregate analytics write failed")


def create_http_app(flask_app):
    bind_app(flask_app)
    mcp_app = server.streamable_http_app(streamable_http_path="/mcp", json_response=True,
                                         stateless_http=True, max_request_body_size=256 * 1024,
                                         max_sessions=1000, host="0.0.0.0")

    @asynccontextmanager
    async def lifespan(app):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    combined = Starlette(routes=[*mcp_app.routes, Mount("/", app=WSGIMiddleware(flask_app))],
                         lifespan=lifespan)
    rate = int(os.getenv("MCP_RATE_LIMIT_PER_MINUTE", "60"))
    return AggregateUsageMiddleware(RateLimitMiddleware(combined, rate), flask_app)


def main():
    bind_app(_app())
    server.run(transport="stdio")


if __name__ == "__main__":
    main()

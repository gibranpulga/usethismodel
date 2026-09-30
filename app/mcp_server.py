"""Read-only MCP facade over the existing UseThisModel SQLite catalogue."""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import logging
import os
import sqlite3
import threading
import time
from collections import OrderedDict
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
from .domain import compatible_route_rows
from .public import slugify
from .query import (
    modality_category,
    normalize_context,
    offer_rows,
    plan_rows,
    route_rows,
    source_rows,
)

SERVER_NAME = "usethismodel"
SERVER_VERSION = "1.0.0"
MAX_LIMIT = 50
COMPATIBLE = {"COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION", "PARTIAL"}
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

server = MCPServer(
    SERVER_NAME,
    title="UseThisModel",
    version=SERVER_VERSION,
    website_url="https://usethismodel.com/mcp-info",
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
    if offset < 0:
        raise ToolError("cursor must be a non-negative integer returned by a previous call")
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
                            "type": modality_category(row["modality"], row["canonical_name"]),
                            "raw_modality": row["modality"], "open_weights": bool(row["open_weights"]),
                            "identity_kind": row["identity_kind"],
                            "identity_status": "UNRESOLVED" if row["identity_kind"] == "UNKNOWN" else "VERIFIED"},
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
        "access_semantics": row["access_semantics"],
        "access_requirement": row["access_requirement"],
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


_compatibility_cache: OrderedDict[tuple, tuple[float, list[dict[str, Any]]]] = OrderedDict()
_compatibility_cache_lock = threading.Lock()
_compatibility_key_locks: OrderedDict[tuple, threading.Lock] = OrderedDict()
_COMPATIBILITY_CACHE_ENTRIES = 4


def _compatibility_cache_key(db, filters, harness_name, workflow_name, require_mcp):
    if not harness_name and not workflow_name:
        return None
    snapshot = db.execute("""SELECT group_concat(digest, ',') FROM (
      SELECT digest FROM applied_snapshots
      WHERE applied_at=(SELECT MAX(applied_at) FROM applied_snapshots) ORDER BY digest)""").fetchone()
    if not snapshot:
        return None
    database_path = db.execute("PRAGMA database_list").fetchone()[2]
    stable_filters = tuple(sorted((str(key), str(value)) for key, value in filters.items()))
    return (database_path, snapshot[0], stable_filters, harness_name, workflow_name, require_mcp)


def _cached_compatibility(key):
    if key is None:
        return None
    with _compatibility_cache_lock:
        entry = _compatibility_cache.get(key)
        if entry and entry[0] > time.monotonic():
            _compatibility_cache.move_to_end(key)
            return copy.deepcopy(entry[1])
        if entry:
            del _compatibility_cache[key]
    return None


def _cache_compatibility(key, rows):
    if key is None:
        return
    duration = max(0, int(os.getenv("MCP_COMPATIBILITY_CACHE_SECONDS", "30")))
    if not duration:
        return
    with _compatibility_cache_lock:
        _compatibility_cache[key] = (time.monotonic() + duration, copy.deepcopy(rows))
        _compatibility_cache.move_to_end(key)
        while len(_compatibility_cache) > _COMPATIBILITY_CACHE_ENTRIES:
            _compatibility_cache.popitem(last=False)


def _compatibility_compute_lock(key):
    if key is None:
        return None
    with _compatibility_cache_lock:
        lock = _compatibility_key_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _compatibility_key_locks[key] = lock
        _compatibility_key_locks.move_to_end(key)
        while len(_compatibility_key_locks) > 32:
            removable = next((old for old, value in _compatibility_key_locks.items()
                              if old != key and not value.locked()), None)
            if removable is None:
                break
            del _compatibility_key_locks[removable]
        return lock


def _routes(db, filters: dict[str, Any], harness_name: str | None = None,
            workflow_name: str | None = None, require_mcp: bool = False) -> list[dict[str, Any]]:
    harness = _harness(db, harness_name)
    if harness_name and not harness:
        raise ToolError(f"Unknown harness: {harness_name}")
    workflow = _workflow(db, workflow_name)
    if workflow_name and not workflow:
        raise ToolError(f"Unknown workflow: {workflow_name}")
    cache_key = _compatibility_cache_key(db, filters, harness_name, workflow_name, require_mcp)
    cached = _cached_compatibility(cache_key)
    if cached is not None:
        return cached
    compute_lock = _compatibility_compute_lock(cache_key)
    if compute_lock:
        compute_lock.acquire()
        cached = _cached_compatibility(cache_key)
        if cached is not None:
            compute_lock.release()
            return cached
    try:
        result = _calculate_routes(db, filters, harness, workflow, require_mcp)
        _cache_compatibility(cache_key, result)
        return result
    finally:
        if compute_lock:
            compute_lock.release()


def _calculate_routes(db, filters, harness, workflow, require_mcp):
    if not harness and not workflow:
        result, after_id = [], 0
        while True:
            page = route_rows(db, {**filters, "_scan_by_id": True,
                                   "_after_offering_id": after_id, "limit": 500, "offset": 0})
            result.extend(_route_json(row) for row in page)
            if len(page) < 500:
                return result
            after_id = page[-1]["offering_id"]
    if harness:
        rows = compatible_route_rows(db, filters, harness["id"],
                                     workflow["id"] if workflow else None,
                                     require_mcp or workflow is not None)
        return [_route_json(row, {"harness": harness["name"], **row["_compatibility"]}) for row in rows]
    hosts = db.execute("""SELECT DISTINCT h.* FROM workflow_harness_compatibility whc
      JOIN workflow_integrations wi ON wi.id=whc.integration_id
      JOIN harnesses h ON h.id=whc.harness_id WHERE wi.workflow_id=?
      AND whc.state IN ('YES','CONFIGURATION','PARTIAL')""", (workflow["id"],)).fetchall()
    found = {}
    for candidate_harness in hosts:
        for row in compatible_route_rows(db, filters, candidate_harness["id"], workflow["id"], True):
            if row["offering_id"] not in found:
                found[row["offering_id"]] = _route_json(
                    row, {"harness": candidate_harness["name"], **row["_compatibility"]}
                )
    return list(found.values())


def _filters(query=None, provider=None, tools=None, free=None, included=None, open_weights=None,
             min_context=None, max_input_price=None, max_output_price=None,
             model_id=None, route_id=None, model_type=None, sort=None):
    values = {"q": query, "provider": provider,
              "context": normalize_context(min_context) if min_context is not None else None,
              "input_max": max_input_price, "output_max": max_output_price,
              "model_id": model_id, "offering_id": route_id, "type": model_type,
              "sort": sort}
    if tools is not None:
        values["tools"] = "1" if tools else "0"
    if free is not None:
        values["free"] = "1" if free else "0"
    if included is not None:
        values["included"] = "1" if included else "0"
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
        if not any((query, tools, free, open_weights, model_type)):
            for row in db.execute("""SELECT m.canonical_name name,m.canonical_slug slug,m.modality type,
               m.open_weights,m.identity_kind FROM models m WHERE NOT EXISTS
                (SELECT 1 FROM provider_offerings o WHERE o.model_id=m.id) ORDER BY m.canonical_name"""):
                grouped.setdefault(row["slug"], {"name":row["name"],"slug":row["slug"],
                                  "type":modality_category(row["type"],row["name"]),"raw_modality":row["type"],
                                  "open_weights":bool(row["open_weights"]),"identity_kind":row["identity_kind"],
                                  "identity_status":"UNRESOLVED" if row["identity_kind"] == "UNKNOWN" else "VERIFIED",
                                  "routes":[]})
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
                           included: bool | None = None,
                           min_context: str | int | None = None,
                           max_input_price: Price | None = None,
                           max_output_price: Price | None = None,
                           harness: str | None = None, limit: Limit = 10,
                           cursor: str | None = None) -> dict[str, Any]:
    """Find exact provider routes by model, provider, price, context, tools, or harness."""
    limit, offset = _page(limit, cursor)
    with _app().app_context():
        routes = _routes(get_db(), _filters(query=query, provider=provider, tools=tools,
                                            free=free, included=included, min_context=min_context,
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
                         min_context: str | int | None = None,
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
    """Find routes with public $0 API/free-tier access; paid subscription access is excluded."""
    limit, offset = _page(limit, cursor)
    with _app().app_context():
        return _paged(_routes(get_db(), _filters(free=True, tools=tools), harness), limit, offset,
                      definition="Free means the route records both input and output as USD 0 and does not require a paid subscription. Terms and rate limits may apply.")


@server.tool(title="Find subscription-included routes", annotations=READ_ONLY, structured_output=True)
def find_subscription_included_routes(tools: bool = False, harness: str | None = None,
                                      limit: Limit = 10, cursor: str | None = None) -> dict[str, Any]:
    """Find routes whose usage is included in a paid provider subscription."""
    limit, offset = _page(limit, cursor)
    with _app().app_context():
        return _paged(_routes(get_db(), _filters(included=True, tools=tools), harness), limit, offset,
                      definition="Requires the listed provider subscription; zero incremental token price is not free access.")


@server.tool(title="Find tool-capable models", annotations=READ_ONLY, structured_output=True)
def find_tool_capable_models(harness: str | None = None,
                             min_context: str | int | None = None,
                             limit: Limit = 10, cursor: str | None = None) -> dict[str, Any]:
    """Find provider routes with explicit tool-calling support."""
    limit, offset = _page(limit, cursor)
    with _app().app_context():
        return _paged(_routes(get_db(), _filters(tools=True, min_context=min_context), harness), limit, offset)


@server.tool(title="Find models for harness", annotations=READ_ONLY, structured_output=True)
def find_models_for_harness(harness: str, tools: bool = False, require_mcp: bool = False,
                            min_context: str | int | None = None,
                            limit: Limit = 10, cursor: str | None = None) -> dict[str, Any]:
    """Find routes compatible with Hermes, Codex CLI, OpenCode, Pi, or another known harness."""
    limit, offset = _page(limit, cursor)
    with _app().app_context():
        routes = _routes(get_db(), _filters(tools=tools, min_context=min_context),
                         harness, require_mcp=require_mcp)
        return _paged(routes, limit, offset, harness=harness, mcp_required=require_mcp)


@server.tool(title="Find models for workflow", annotations=READ_ONLY, structured_output=True)
def find_models_for_workflow(workflow: str, harness: str | None = None,
                             min_context: str | int | None = None,
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
                   benchmark: str | None = None, version: str | None = None,
                   compare_models: Annotated[list[str] | None, Field(max_length=6)] = None,
                   limit: Limit = 10, cursor: str | None = None) -> dict[str, Any]:
    """Get source-backed benchmark results, optionally limited to shared comparable runs."""
    limit, offset = _page(limit, cursor)
    with _app().app_context():
        db = get_db()
        params, clauses = [], []
        if current_only:
            clauses.append("b.is_current=1")
        if benchmark:
            clauses.append("b.name=?")
            params.append(benchmark)
        if version:
            clauses.append("b.version=?")
            params.append(version)
        if model:
            found = _model(db, model)
            if not found:
                raise ToolError(f"Unknown model: {model}")
            clauses.append("br.model_id=?")
            params.append(found["id"])
        comparison_ids = []
        for value in compare_models or []:
            found = _model(db, value)
            if not found:
                raise ToolError(f"Unknown model: {value}")
            comparison_ids.append(found["id"])
        comparison_ids = list(dict.fromkeys(comparison_ids))
        if compare_models and len(comparison_ids) < 2:
            raise ToolError("Pass at least two distinct canonical models to compare benchmark results.")
        if comparison_ids:
            clauses.append(f"br.model_id IN ({','.join('?' for _ in comparison_ids)})")
            params.extend(comparison_ids)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = [dict(row) for row in db.execute(f"""SELECT b.id benchmark_id,b.name,b.version,b.category,b.description,
          b.is_current,b.methodology_url,b.published_at,b.last_verified_at,m.id model_id,
          m.canonical_name model,m.canonical_slug model_slug,br.model_version,
          br.score,br.metric,br.task_subset,br.harness_name,br.harness_version,br.scaffold,
          br.reasoning_setting,br.tool_policy,br.network_policy,br.step_budget,br.token_budget,
          br.time_budget_seconds,br.attempts_per_task,br.grader_version,br.confidence_interval,
          br.evaluated_at,br.confidence,s.name source_name,s.url source_url
          FROM benchmarks b LEFT JOIN benchmark_results br ON br.benchmark_id=b.id
          LEFT JOIN models m ON m.id=br.model_id LEFT JOIN sources s ON s.id=COALESCE(br.source_id,b.source_id)
          {where} ORDER BY b.name,b.version,br.metric,br.task_subset,br.harness_name,
            br.harness_version,br.scaffold,br.reasoning_setting,br.tool_policy,br.network_policy,
            br.attempts_per_task,br.grader_version,br.score DESC""", params)]
        for row in rows:
            row["sources"] = ([{"name": row.pop("source_name"), "url": row.pop("source_url")}]
                              if row.get("source_url") else [])
        from .benchmark_queries import comparable_groups
        groups = comparable_groups(rows) if comparison_ids else []
        return _paged(rows, limit, offset, compared_models=compare_models or [],
                      comparable_groups=groups,
                      caveat="Scores compare only within the same benchmark version, metric, task and published run configuration. Unknown configuration does not establish comparability.")


@server.tool(title="Calculate route cost", annotations=READ_ONLY, structured_output=True)
def calculate_cost(route_id: int, input_tokens: PositiveInt = 0,
                   output_tokens: PositiveInt = 0, cache_read_tokens: PositiveInt = 0) -> dict[str, Any]:
    """Calculate token cost using separately published input/output/cache prices."""
    with _app().app_context():
        routes = _routes(get_db(), _filters(route_id=route_id))
        if not routes:
            raise ToolError(f"Unknown route_id: {route_id}")
        route = routes[0]
        from .costing import estimate_token_cost
        prices = {}
        for price_row in get_db().execute("SELECT price_type,amount,unit,context_threshold FROM pricing_records WHERE offering_id=? AND valid_until IS NULL", (route_id,)):
            price = prices.setdefault(price_row["price_type"], {"amount": price_row["amount"], "unit": price_row["unit"]})
            if price_row["context_threshold"] is not None:
                price["tiered"] = True
        estimate = estimate_token_cost(prices, {"input": input_tokens, "output": output_tokens,
             "cache_read": cache_read_tokens}, batch=False)
        if estimate["cost"] is None:
            raise ToolError("Price is unknown for requested token classes: " + ", ".join(estimate["missing"]))
        cost = estimate["cost"]
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
            "SELECT canonical_name name,canonical_slug slug,modality type,released_at release_date,status FROM models ORDER BY canonical_name LIMIT 1000")])


@server.resource("utm://providers", title="Providers", mime_type="application/json")
def providers_resource() -> str:
    with _app().app_context():
        return _resource_json([dict(row) for row in get_db().execute(
            "SELECT id,name,website_url FROM providers WHERE canonical_provider_id IS NULL ORDER BY name LIMIT 1000")])


@server.resource("utm://harnesses", title="Harnesses", mime_type="application/json")
def harnesses_resource() -> str:
    with _app().app_context():
        return _resource_json([dict(row) for row in get_db().execute(
            """SELECT h.id,h.name,h.interfaces,h.supports_mcp,h.version_verified_at last_verified_at,
              (SELECT MAX(dm.last_checked_at) FROM harness_claims hc JOIN documentation_monitor_state dm ON dm.source_id=hc.source_id WHERE hc.harness_id=h.id) documentation_last_checked_at
              FROM harnesses h ORDER BY h.name LIMIT 1000""")])


@server.resource("utm://offers", title="Current offers", mime_type="application/json")
def offers_resource() -> str:
    return _resource_json(get_current_deals(limit=50)["items"])


@server.resource("utm://benchmark-metadata", title="Benchmark metadata", mime_type="application/json")
def benchmarks_resource() -> str:
    with _app().app_context():
        return _resource_json([dict(row) for row in get_db().execute(
            "SELECT name,version,category,description,methodology_url,last_verified_at FROM benchmarks ORDER BY name,version LIMIT 1000")])


class RateLimitMiddleware:
    """Shared SQLite fixed-window guard; XFF is honored only behind trusted proxies."""

    def __init__(self, app, requests_per_minute: int, flask_app=None):
        self.app = app
        self.limit = max(1, requests_per_minute)
        self.flask_app = flask_app
        self.trusted = []
        for item in os.getenv("TRUSTED_PROXY_CIDRS", "").split(","):
            try:
                self.trusted.append(ipaddress.ip_network(item.strip(), strict=False))
            except ValueError:
                logging.getLogger("utm.security").error("Ignoring invalid trusted proxy CIDR")

    def _client(self, scope):
        peer = (scope.get("client") or ("unknown", 0))[0]
        try:
            peer_ip = ipaddress.ip_address(peer)
        except ValueError:
            return peer
        if not any(peer_ip in network for network in self.trusted):
            return peer
        forwarded = next((v.decode("latin1") for k, v in scope.get("headers", []) if k.lower() == b"x-forwarded-for"), "")
        chain = []
        for value in forwarded.split(","):
            try:
                chain.append(ipaddress.ip_address(value.strip()))
            except ValueError:
                return peer
        current = peer_ip
        for candidate in reversed(chain):
            if not any(current in network for network in self.trusted):
                break
            current = candidate
        return str(current)

    def _allow(self, client, window, limit):
        if self.flask_app is None:
            # Local/test fallback. Production always supplies Flask config and uses
            # the shared SQLite counter across workers.
            return True, 1
        digest = hashlib.sha256(client.encode()).hexdigest()
        path = self.flask_app.config["DATABASE"]
        with sqlite3.connect(path, timeout=2) as db:
            db.execute("INSERT INTO rate_limit_windows(client_hash,window_start,request_count) VALUES(?,?,1) ON CONFLICT(client_hash,window_start) DO UPDATE SET request_count=request_count+1", (digest, window))
            count = db.execute("SELECT request_count FROM rate_limit_windows WHERE client_hash=? AND window_start=?", (digest, window)).fetchone()[0]
            db.execute("DELETE FROM rate_limit_windows WHERE window_start<?", (window - 120,))
            return count <= limit, count

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        protected = path == "/mcp" or path.startswith("/mcp/") or path == "/api/v1" or path.startswith("/api/v1/")
        if scope["type"] != "http" or not protected:
            await self.app(scope, receive, send)
            return
        client = self._client(scope)
        window = int(time.time() // 60) * 60
        limit = max(1, int(os.getenv("PUBLIC_API_RATE_LIMIT_PER_MINUTE", "120"))) if path.startswith("/api/") else self.limit
        allowed, _count = self._allow(client, window, limit)
        if not allowed:
            logging.getLogger("utm.security").warning("mcp_rate_limit_hit")
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
        path = scope.get("path", "")
        if scope["type"] == "http" and (path == "/mcp" or path.startswith("/mcp/")):
            try:
                from .analytics import record
                from .db import get_db as writable_db
                with self.flask_app.app_context():
                    record(writable_db(), "mcp_request", scope.get("method", "UNKNOWN"))
            except Exception:
                self.flask_app.logger.exception("MCP aggregate analytics write failed")


class PublicRequestObservabilityMiddleware:
    """Log slow public MCP/API requests without reading request bodies or queries."""

    def __init__(self, app):
        self.app = app
        self.threshold = max(0.1, float(os.getenv("SLOW_PUBLIC_REQUEST_SECONDS", "1.0")))

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        protected = path == "/mcp" or path.startswith("/mcp/") or path == "/api/v1" or path.startswith("/api/v1/")
        if scope["type"] != "http" or not protected:
            await self.app(scope, receive, send)
            return
        started = time.monotonic()
        status_code = 500
        async def observed_send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)
        await self.app(scope, receive, observed_send)
        elapsed = time.monotonic() - started
        if elapsed >= self.threshold:
            label = "/mcp" if path.startswith("/mcp") else "/api/v1"
            logging.getLogger("utm.performance").warning(
                "public_request_slow path=%s method=%s status=%s duration_ms=%d",
                label, scope.get("method", "UNKNOWN"), status_code, round(elapsed * 1000))


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
    limited = RateLimitMiddleware(combined, rate, flask_app)
    observed = PublicRequestObservabilityMiddleware(limited)
    return AggregateUsageMiddleware(observed, flask_app)


def main():
    bind_app(_app())
    server.run(transport="stdio")


if __name__ == "__main__":
    main()

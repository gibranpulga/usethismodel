import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from starlette.testclient import TestClient

from app import create_app
from app.data_snapshot import apply_snapshot
from app.db import get_db as app_get_db
from app.mcp_server import MAX_LIMIT, bind_app, create_http_app, get_db, server


@pytest.fixture()
def mcp_app(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "mcp.sqlite3")})
    bind_app(app)
    return app


def call(name, arguments):
    return asyncio.run(server.call_tool(name, arguments))


def test_tool_schemas_are_bounded_and_read_only(mcp_app):
    tools = asyncio.run(server.list_tools())

    assert len(tools) == 17
    assert {tool.name for tool in tools} >= {
        "search_models", "get_model", "search_provider_routes", "compare_models",
        "compare_routes", "find_cheapest_routes", "find_free_models", "find_subscription_included_routes",
        "find_tool_capable_models", "find_models_for_harness", "find_models_for_workflow",
        "get_compatibility", "get_current_deals", "get_new_releases", "get_benchmarks",
        "calculate_cost", "get_plan_options",
    }
    for tool in tools:
        dumped = tool.model_dump(by_alias=True)
        assert dumped["annotations"] == {
            "title": None,
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
        if "limit" in dumped["inputSchema"].get("properties", {}):
            assert dumped["inputSchema"]["properties"]["limit"]["maximum"] == MAX_LIMIT

    with mcp_app.app_context():
        assert get_db().execute("PRAGMA query_only").fetchone()[0] == 1


def test_filters_pagination_sources_and_freshness(mcp_app):
    first = call("find_tool_capable_models", {"limit": 2}).structured_content
    second = call("find_tool_capable_models", {
        "limit": 2, "cursor": first["page"]["next_cursor"]
    }).structured_content

    assert len(first["items"]) == 2
    assert first["items"][0]["route_id"] != second["items"][0]["route_id"]
    for route in first["items"]:
        assert route["capabilities"]["tools"] == "YES"
        assert route["last_verified_at"]
        assert route["sources"]
        assert all(source["url"].startswith("http") for source in route["sources"])

    free = call("find_free_models", {"tools": True, "limit": 10}).structured_content
    assert free["items"]
    assert all(route["price_usd_per_million_tokens"]["input"] == 0 for route in free["items"])
    assert all(route["price_usd_per_million_tokens"]["output"] == 0 for route in free["items"])


def test_natural_search_applies_harness_and_price_facets(mcp_app):
    free_tools = call("search_provider_routes", {"query": "free tools", "limit": 10}).structured_content
    assert free_tools["items"]
    assert all(route["free_status"] == "FREE" and route["capabilities"]["tools"] == "YES"
               for route in free_tools["items"])
    hermes = call("search_provider_routes", {"query": "works with Hermes", "limit": 5}).structured_content
    assert hermes["items"]
    assert all(route["compatibility"]["harness"] == "Hermes Agent" for route in hermes["items"])


def test_natural_unreal_mcp_search_requires_tool_capable_routes(mcp_app):
    result = call("search_provider_routes", {"query": "OpenCode Unreal MCP", "limit": 20}).structured_content
    assert result["items"]
    assert all(route["compatibility"]["harness"] == "OpenCode" for route in result["items"])
    assert all(route["capabilities"]["tools"] == "YES" for route in result["items"])


def test_route_price_evidence_includes_source_freshness_and_price_terms(mcp_app):
    from pathlib import Path
    with mcp_app.app_context():
        apply_snapshot(app_get_db(), Path(__file__).resolve().parents[1] / "data" / "catalog.json")
    result = call("search_provider_routes", {"provider": "DeepSeek", "query": "V4 Pro", "limit": 10}).structured_content
    route = next(item for item in result["items"] if item["route_id"] == 1085)
    evidence = {item["price_type"]: item for item in route["price_evidence"]}
    assert evidence["INPUT"]["amount"] == 0.66
    assert evidence["INPUT"]["source_url"] == "https://api-docs.deepseek.com/quick_start/pricing/"
    assert evidence["INPUT"]["price_observed_at"] == "2026-10-01T00:00:00+00:00"
    assert "peak rate is $1.32" in evidence["INPUT"]["price_note"]


def test_harness_context_and_cost_filters(mcp_app):
    result = call("find_cheapest_routes", {
        "harness": "Hermes", "tools": True, "min_context": 500_000,
        "input_tokens": 1_000_000, "output_tokens": 1_000_000,
    }).structured_content

    assert result["items"]
    costs = [route["calculated_cost_usd"] for route in result["items"]]
    assert costs == sorted(costs)
    assert all(route["limits"]["context_tokens"] >= 500_000 for route in result["items"])
    assert all(route["compatibility"]["harness"] == "Hermes Agent" for route in result["items"])


def test_bad_input_and_unknown_entities_are_errors(mcp_app):
    with pytest.raises(ToolError, match="less than or equal to 50"):
        call("search_models", {"limit": 51})
    with pytest.raises(ToolError, match="cursor must be a non-negative integer"):
        call("search_models", {"cursor": "later"})
    with pytest.raises(ToolError, match="Unknown model"):
        call("get_model", {"model": "not-a-real-model"})
    with pytest.raises(ToolError, match="Unknown route_id"):
        call("calculate_cost", {"route_id": 999999, "input_tokens": 1})
    with pytest.raises(ToolError, match="Unknown harness"):
        call("find_models_for_harness", {"harness": "not-a-harness"})


def test_resources_are_small_public_catalogues(mcp_app):
    resources = asyncio.run(server.list_resources())
    assert {str(resource.uri) for resource in resources} == {
        "utm://models", "utm://providers", "utm://harnesses", "utm://offers",
        "utm://benchmark-metadata",
    }
    for resource in resources:
        content = asyncio.run(server.read_resource(resource.uri))
        assert len(str(content)) < 100_000


def test_streamable_http_initializes_and_site_is_still_served(mcp_app, monkeypatch):
    monkeypatch.setenv("MCP_RATE_LIMIT_PER_MINUTE", "60")
    application = create_http_app(mcp_app)
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                   "clientInfo": {"name": "pytest", "version": "1"}},
    }
    with TestClient(application) as client:
        assert client.get("/mcp-info").status_code == 200
        response = client.post(
            "/mcp", json=payload,
            headers={"accept": "application/json, text/event-stream"},
        )
    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "usethismodel"
    assert response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert response.headers["content-security-policy"].startswith("default-src 'self'")


def test_public_mcp_rate_limit(mcp_app, monkeypatch):
    monkeypatch.setenv("MCP_RATE_LIMIT_PER_MINUTE", "2")
    application = create_http_app(mcp_app)
    with TestClient(application) as client:
        assert client.post("/mcp", json={}, headers={"X-Forwarded-For": "203.0.113.1"}).status_code != 429
        assert client.post("/mcp", json={}, headers={"X-Forwarded-For": "198.51.100.2"}).status_code != 429
        limited = client.post("/mcp", json={}, headers={"X-Forwarded-For": "192.0.2.3"})
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert limited.json()["error"] == "rate_limit_exceeded"
    assert limited.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    assert limited.headers["x-content-type-options"] == "nosniff"
    assert limited.headers["x-robots-tag"] == "noindex, nofollow"


def test_mcp_compatibility_has_no_catalog_candidate_ceiling(mcp_app):
    from app import mcp_server
    assert not hasattr(mcp_server, "MAX_CANDIDATES")
    assert mcp_server._page(10, "10001") == (10, 10001)


def test_mcp_route_scan_returns_catalogs_larger_than_ten_thousand(mcp_app):
    from app.mcp_server import _calculate_routes

    with mcp_app.app_context():
        db = get_db()
        db.execute("PRAGMA query_only=OFF")
        seed = db.execute("""SELECT model_id,provider_id,api_model_id,context_limit,
          max_output_tokens,tool_support,structured_output_support,free_status,source_id
          FROM provider_offerings LIMIT 1""").fetchone()
        rows = [tuple(seed[:2]) + (f"scale-test-{i}",) + tuple(seed[3:]) for i in range(10_001)]
        db.executemany("""INSERT INTO provider_offerings
          (model_id,provider_id,api_model_id,context_limit,max_output_tokens,tool_support,
           structured_output_support,free_status,source_id) VALUES(?,?,?,?,?,?,?,?,?)""", rows)
        db.commit()
        result = _calculate_routes(db, {}, None, None, False)
        db.execute("PRAGMA query_only=ON")
    assert len(result) > 10_000


def test_mcp_compatibility_exposes_protocol_evidence(mcp_app):
    with mcp_app.app_context():
        db = app_get_db()
        apply_snapshot(db, "data/catalog.json")
        route_id = db.execute("""SELECT o.id FROM provider_offerings o
          JOIN providers p ON p.id=o.provider_id WHERE p.name='DeepSeek'
          AND o.tool_support='YES' LIMIT 1""").fetchone()[0]
        result = call("get_compatibility", {"harness": "OpenCode", "route_id": route_id})
    compatibility = result.structured_content["items"][0]["compatibility"]
    assert compatibility["protocol_evidence"]["protocol"] == "OPENAI_CHAT_COMPLETIONS"
    assert any("deepseek.com" in source["url"] for source in compatibility["sources"])


def test_compatibility_result_cache_is_digest_keyed_and_copy_safe(mcp_app):
    from app.mcp_server import (
        _cache_compatibility,
        _cached_compatibility,
        _compatibility_cache,
        _compatibility_cache_key,
    )
    with mcp_app.app_context():
        db = get_db()
        db.execute('PRAGMA query_only = OFF')
        db.execute("INSERT INTO applied_snapshots(digest) VALUES('cache-test-one')")
        first = _compatibility_cache_key(db, {'tools': '1'}, 'Hermes Agent', None, False)
        _compatibility_cache.clear()
        _cache_compatibility(first, [{'route': 1}])
        value = _cached_compatibility(first)
        value[0]['route'] = 99
        assert _cached_compatibility(first) == [{'route': 1}]
        db.execute("INSERT INTO applied_snapshots(digest) VALUES('cache-test-two')")
        second = _compatibility_cache_key(db, {'tools': '1'}, 'Hermes Agent', None, False)
        assert first != second
        db.execute('PRAGMA query_only = ON')


def test_representative_mcp_calls_load_smoke(mcp_app):
    # Bounded representative call mix; catches accidental context-size/query blowups.
    for name, args in (("search_models", {"query": "gemini", "limit": 10}),
                       ("search_provider_routes", {"query": "openai", "limit": 10}),
                       ("get_benchmarks", {"limit": 10}),
                       ("get_plan_options", {"limit": 10})):
        result = call(name, args).structured_content
        assert len(result["items"]) <= 10

import json
import re
import sqlite3
from pathlib import Path
from xml.etree import ElementTree

import pytest

from app import create_app
from app.data_snapshot import apply_snapshot
from app.db import get_db
from app.domain import canonical_model, compatibility_for, compatible_route_rows
from app.query import interpret_search, price_history, route_rows


@pytest.fixture()
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3"),
                       "PUBLIC_BASE_URL": "https://usethismodel.com"})


@pytest.fixture()
def client(app):
    return app.test_client()


def test_database_initializes_all_migrations(app):
    database = app.config["DATABASE"]
    with sqlite3.connect(database) as connection:
        migrations = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }

        assert migrations == [(i,) for i in range(1, 24)]
    assert {
        "models",
        "providers",
        "routes",
        "harnesses",
        "offers",
        "use_cases",
        "route_capabilities",
        "compatibility_notes",
        "benchmark_measurements",
        "sources",
        "labs",
        "provider_offerings",
        "pricing_records",
        "plans",
        "harness_provider_compatibility",
        "harness_mcp_capabilities",
        "harness_model_overrides",
        "model_use_case_scores",
        "benchmarks",
        "benchmark_results",
        "data_change_log",
        "model_media_features",
        "harness_claims",
        "harness_access_methods",
        "workflows",
        "workflow_integrations",
        "workflow_harness_compatibility",
        "route_compatibility_evidence",
        "plan_harness_compatibility",
        "model_access_routes",
        "analytics_daily",
    } <= tables


def test_health_checks_sqlite(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json["status"] == "ok"
    assert response.json["database"] == "sqlite"


def test_homepage_satisfies_public_monitor_content_checks(client):
    from scripts.monitor_public import REQUIRED
    response = client.get('/')
    assert response.status_code == 200
    assert all(marker in response.data for marker in REQUIRED['homepage'])


def test_homepage_release_cards_expose_date_provenance_and_capabilities(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "New models this week" in body
    assert "Release provenance:" in body
    assert "Tools:" in body
    assert 'href="/releases"' in body


def test_finder_harness_select_uses_canonical_slugs_and_modality_labels(client):
    response = client.get("/models")
    body = response.get_data(as_text=True)
    assert 'value="hermes-agent"' in body
    assert "text-&gt;text" not in body
    assert "Text LLM" in body or "Multimodal LLM" in body


def test_true_free_and_subscription_access_stay_visibly_distinct(client):
    body = client.get("/models?included=1").get_data(as_text=True)
    assert "Included with" in body or "SUBSCRIPTION REQUIRED" in body
    free_body = client.get("/models?free=1").get_data(as_text=True)
    assert "FREE API" in free_body or "No route matches" in free_body
    assert "FREE route" not in free_body


def test_plan_catalog_preserves_vague_limits_and_access_routes(client):
    response = client.get("/plans?harness=OpenCode&coding=1")

    assert response.status_code == 200
    assert b"GLM Coding Plan" in response.data
    assert b"Exact token equivalent" in response.data
    assert b"documented third party" in response.data
    assert b"Z.ai PAYG API" in response.data
    assert b"OpenRouter" in response.data

    api = client.get("/api/v1/plans?subscription=true&coding=true")
    assert api.status_code == 200
    assert api.json["meta"]["count"] >= 10
    assert all("quota_description" in plan for plan in api.json["data"])


def test_calculator_compares_without_inventing_break_even(client, app):
    with app.app_context():
        plan_id = get_db().execute(
            "SELECT id FROM plans WHERE name='GLM Coding Plan Lite'"
        ).fetchone()[0]

    response = client.get(f"/calculator?plan_id={plan_id}&input_tokens=1000000&output_tokens=250000")

    assert response.status_code == 200
    assert b"Exact PAYG estimates" in response.data
    assert b"Exact token equivalent: <b>unknown</b>" in response.data
    assert b"No break-even is claimed" in response.data


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/models",
        "/plans",
        "/providers",
        "/harnesses",
        "/workflows",
        "/workflows/unreal-engine",
        "/workflows/reaper",
        "/compatibility",
        "/deals",
        "/releases",
        "/benchmarks",
        "/use-cases",
        "/compare",
        "/calculator",
        "/rankings",
        "/my-setup",
        "/mcp-info",
    ],
)
def test_foundation_sections_are_available(client, path):
    response = client.get(path)

    assert response.status_code == 200


def test_canonicalization_keeps_provider_aliases(app):
    with app.app_context():
        db = get_db()
        provider = db.execute("SELECT id FROM providers WHERE name='Z.ai'").fetchone()[0]
        model = canonical_model(db, provider, "glm-5.3")
    assert model["canonical_slug"] == "zhipuai/glm-5.3"


def test_offering_price_and_source_provenance_are_separate(app):
    with app.app_context():
        db = get_db()
        result = db.execute("""SELECT o.api_model_id, count(pr.id) prices, count(DISTINCT pr.source_id) sources
            FROM provider_offerings o JOIN pricing_records pr ON pr.offering_id=o.id
            WHERE o.api_model_id='glm-5.3' GROUP BY o.id""").fetchone()
    assert result["prices"] >= 2
    assert result["sources"] == 1


def test_compatibility_is_fact_derived_and_configuration_aware(app):
    with app.app_context():
        db = get_db()
        harness = db.execute("SELECT id FROM harnesses WHERE name='OpenCode'").fetchone()[0]
        offering = db.execute("""SELECT o.id FROM provider_offerings o JOIN providers p ON p.id=o.provider_id
            WHERE p.name='Z.ai' AND o.api_model_id='glm-5.3'""").fetchone()[0]
        result = compatibility_for(db, harness, offering, mcp_workflow=True)
    assert result["status"] == "COMPATIBLE_WITH_CONFIGURATION"
    assert "Tool calling: Yes" in result["explanation"]


@pytest.mark.parametrize(
    "harness,provider,protocol",
    [
        ("OpenCode", "OpenAI", "OPENAI_CHAT_COMPLETIONS"),
        ("OpenCode", "Anthropic", "ANTHROPIC_MESSAGES"),
        ("OpenCode", "DeepSeek", "OPENAI_CHAT_COMPLETIONS"),
        ("OpenCode", "Z.AI", "OPENAI_CHAT_COMPLETIONS"),
        ("Pi", "Google", "GOOGLE_GEMINI_NATIVE"),
        ("Hermes Agent", "DeepSeek", "OPENAI_CHAT_COMPLETIONS"),
        ("Codex CLI", "OpenAI", "OPENAI_RESPONSES"),
    ],
)
def test_direct_provider_compatibility_requires_matching_protocol_evidence(
    app, harness, provider, protocol
):
    with app.app_context():
        db = get_db()
        apply_snapshot(db, Path(__file__).resolve().parents[1] / "data" / "catalog.json")
        harness_id = db.execute("SELECT id FROM harnesses WHERE name=?", (harness,)).fetchone()[0]
        offering = db.execute(
            """SELECT o.id FROM provider_offerings o JOIN providers p ON p.id=o.provider_id
               WHERE p.name=? AND o.tool_support='YES' AND NOT EXISTS (
                 SELECT 1 FROM route_compatibility_evidence e
                 WHERE e.harness_id=? AND e.offering_id=o.id) LIMIT 1""",
            (provider, harness_id),
        ).fetchone()
        assert offering
        result = compatibility_for(db, harness_id, offering["id"])
    assert result["status"] in {"COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION"}
    assert result["derived"] is True
    assert result["protocol_evidence"]["protocol"] == protocol
    assert result["protocol_evidence"]["provider_source_url"].startswith("https://")
    assert result["protocol_evidence"]["harness_verified_at"]


def test_protocol_mismatch_and_incomplete_evidence_remain_unknown(app):
    with app.app_context():
        db = get_db()
        apply_snapshot(db, Path(__file__).resolve().parents[1] / "data" / "catalog.json")
        harness_id = db.execute("SELECT id FROM harnesses WHERE name='Codex CLI'").fetchone()[0]
        offering = db.execute(
            """SELECT o.id FROM provider_offerings o JOIN providers p ON p.id=o.provider_id
               WHERE p.name='Anthropic' LIMIT 1"""
        ).fetchone()
        result = compatibility_for(db, harness_id, offering["id"])
    assert result["status"] == "UNKNOWN"


def test_public_compatibility_api_exposes_both_protocol_sources(app):
    with app.app_context():
        db = get_db()
        apply_snapshot(db, Path(__file__).resolve().parents[1] / "data" / "catalog.json")
    response = app.test_client().get(
        "/api/v1/compatibility?harness=opencode&provider=DeepSeek&limit=1"
    )
    assert response.status_code == 200
    compatibility = response.json["data"][0]["compatibility"]
    assert compatibility["protocol_evidence"]["protocol"] == "OPENAI_CHAT_COMPLETIONS"
    assert any("deepseek.com" in source["url"] for source in compatibility["sources"])
    assert any("opencode.ai" in source["url"] for source in compatibility["sources"])


def test_codex_openrouter_and_claude_gateway_model_restrictions(app):
    with app.app_context():
        db = get_db()
        apply_snapshot(db, Path(__file__).resolve().parents[1] / "data" / "catalog.json")
        codex = db.execute("SELECT id FROM harnesses WHERE name='Codex CLI'").fetchone()[0]
        claude = db.execute("SELECT id FROM harnesses WHERE name='Claude Code'").fetchone()[0]
        openrouter = db.execute("SELECT id FROM providers WHERE name='OpenRouter'").fetchone()[0]
        router_route = db.execute("""SELECT id FROM provider_offerings
          WHERE provider_id=? AND api_model_id='z-ai/glm-5.3'""", (openrouter,)).fetchone()
        codex_result = compatibility_for(db, codex, router_route["id"])
        claude_result = compatibility_for(db, claude, router_route["id"])
        native_claude_route = db.execute("""SELECT o.id FROM provider_offerings o
          JOIN providers p ON p.id=o.provider_id JOIN models m ON m.id=o.model_id
          WHERE p.name='Anthropic' AND lower(m.canonical_name) LIKE '%claude%' LIMIT 1""").fetchone()
        native_claude = compatibility_for(db, claude, native_claude_route["id"])
    assert codex_result["status"] in {"COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION"}
    assert claude_result["status"] == "UNKNOWN"
    assert native_claude["status"] in {"COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION"}


def test_unknown_and_provider_specific_override(app):
    with app.app_context():
        db = get_db()
        harness = db.execute("SELECT id FROM harnesses WHERE name='Aider'").fetchone()[0]
        offering = db.execute(
            "SELECT id,model_id FROM provider_offerings WHERE api_model_id='glm-5.3'"
        ).fetchone()
        assert compatibility_for(db, harness, offering["id"])["status"] == "UNKNOWN"
        db.execute(
            """INSERT INTO harness_model_overrides(harness_id,offering_id,status,reason)
            VALUES(?,?,?,?)""",
            (
                harness,
                offering["id"],
                "NOT_COMPATIBLE",
                "Tested route does not support this harness.",
            ),
        )
        db.commit()
        assert compatibility_for(db, harness, offering["id"])["status"] == "NOT_COMPATIBLE"


def test_official_openrouter_access_derives_route_compatibility(app):
    with app.app_context():
        db = get_db()
        harness = db.execute("SELECT id FROM harnesses WHERE name='Pi'").fetchone()[0]
        offering = db.execute("""SELECT o.id FROM provider_offerings o JOIN providers p ON p.id=o.provider_id
          WHERE p.name='OpenRouter' AND o.tool_support='YES' AND NOT EXISTS
          (SELECT 1 FROM route_compatibility_evidence e WHERE e.harness_id=? AND e.offering_id=o.id) LIMIT 1""", (harness,)).fetchone()
        result = compatibility_for(db, harness, offering["id"])
        assert result["status"] == "COMPATIBLE_WITH_CONFIGURATION"
        assert result["derived"] is True
        assert result["checks"]["tool_call_reliability"] == "UNKNOWN"
        assert result["source"]["url"]

        unsupported = db.execute("SELECT id FROM harnesses WHERE name='Gemini CLI'").fetchone()[0]
        unknown = compatibility_for(db, unsupported, offering["id"])
        assert unknown["status"] == "UNKNOWN"


def test_catalog_detail_pages(client):
    for path in ["/models/1", "/providers/1", "/harnesses/1"]:
        response = client.get(path)
        assert response.status_code == 301
        assert client.get(response.location).status_code == 200


def test_route_specific_mcp_evidence_and_workflow_registry(app, client):
    with app.app_context():
        db = get_db()
        harness = db.execute("SELECT id FROM harnesses WHERE name='OpenCode'").fetchone()[0]
        workflow = db.execute("SELECT id FROM workflows WHERE slug='unreal-engine'").fetchone()[0]
        offering = db.execute("SELECT id FROM provider_offerings WHERE api_model_id='z-ai/glm-5.3'").fetchone()[0]
        result = compatibility_for(db, harness, offering, mcp_workflow=True, workflow_id=workflow)
    assert result["status"] == "COMPATIBLE_WITH_CONFIGURATION"
    assert result["checks"] == {
        "harness_can_use_model": "YES",
        "harness_supports_mcp": "YES",
        "provider_route_tool_calls": "YES",
        "tool_call_reliability": "UNVERIFIED",
        "workflow_host": "CONFIGURATION",
    }
    response = client.get("/compatibility?workflow=unreal-engine&harness=OpenCode&tools=1&context=128000")
    assert response.status_code == 200
    assert b"Harness can use model" in response.data
    assert b"Known tool reliability" in response.data
    assert b"GLM-5.3" in response.data


def test_harness_profiles_expose_sources_and_access_methods(client):
    response = client.get("/harnesses/hermes-agent")
    assert response.status_code == 200
    assert b"0.20.0 installed; upstream 0.21.5" in response.data
    assert b"Openrouter" in response.data
    assert b"Streamable Http" in response.data
    assert b"verified 2026-09-29" in response.data


def test_harness_detail_qualifies_beyond_default_route_page(app):
    with app.app_context():
        db = get_db()
        apply_snapshot(db, Path(__file__).resolve().parents[1] / "data" / "catalog.json")
        harness_id = db.execute("SELECT id FROM harnesses WHERE name='OpenCode'").fetchone()[0]
        default_ids = {route["offering_id"] for route in route_rows(db, {})}
        qualified = compatible_route_rows(db, {}, harness_id)
        display_order = sorted(qualified, key=lambda route: (
            not bool(route["_compatibility"].get("source")),
            route.get("input_price") is None,
            route.get("input_price") or 0,
            route.get("canonical_name", ""),
            route.get("provider_name", ""),
        ))[:24]
        displayed_from_beyond_default = next(
            route for route in display_order if route["offering_id"] not in default_ids
        )
        client = app.test_client()
        response = client.get("/harnesses/opencode")
    assert response.status_code == 200
    assert displayed_from_beyond_default["api_model_id"].encode() in response.data


@pytest.mark.parametrize(
    "harness,provider,api_model_id,expected_access",
    [
        ("OpenCode", "Z.ai", "glm-5.3", "custom OpenAI-compatible endpoint"),
        ("OpenCode", "OpenRouter", "z-ai/glm-5.3", "OpenRouter API key"),
        ("Pi", "OpenRouter", "z-ai/glm-5.3", "OpenRouter API key"),
        ("Hermes Agent", "OpenRouter", "z-ai/glm-5.3", "OpenRouter API key"),
    ],
)
def test_requested_route_cases_are_explicit(app, harness, provider, api_model_id, expected_access):
    with app.app_context():
        db = get_db()
        harness_id = db.execute("SELECT id FROM harnesses WHERE name=?", (harness,)).fetchone()[0]
        offering_id = db.execute("""SELECT o.id FROM provider_offerings o JOIN providers p ON p.id=o.provider_id
          WHERE p.name=? AND o.api_model_id=?""", (provider, api_model_id)).fetchone()[0]
        result = compatibility_for(db, harness_id, offering_id, mcp_workflow=harness != "Codex CLI")
    assert result["checks"]["harness_can_use_model"] == "YES"
    assert result["checks"]["provider_route_tool_calls"] == "YES"
    assert result["access_method"] == expected_access


def test_published_snapshot_contains_all_requested_route_cases():
    root = Path(__file__).resolve().parent.parent / "data" / "snapshot"
    evidence = [row for path in (root / "route_compatibility_evidence").glob("*.json")
                for row in json.loads(path.read_text())]
    access = {(row["access_method"], row["mcp_workflow_status"]) for row in evidence}
    assert len(evidence) >= 8
    providers = [row for path in (root / "harness_provider_compatibility").glob("*.json")
                 for row in json.loads(path.read_text())]
    assert sum(row["support_mode"] not in {"UNKNOWN", "NO"} for row in providers) >= 4
    assert ("DeepSeek API key", "COMPATIBLE") in access
    assert ("OpenAI API key or ChatGPT/Codex subscription", "COMPATIBLE") in access


@pytest.mark.parametrize("harness", ["OpenCode", "Codex CLI"])
def test_unreal_mcp_requested_hosts_are_explicit(app, harness):
    with app.app_context():
        db = get_db()
        count = db.execute("""SELECT COUNT(*) FROM workflow_harness_compatibility whc
          JOIN workflow_integrations wi ON wi.id=whc.integration_id
          JOIN workflows w ON w.id=wi.workflow_id JOIN harnesses h ON h.id=whc.harness_id
          WHERE w.slug='unreal-engine' AND h.name=? AND whc.state='CONFIGURATION'""", (harness,)).fetchone()[0]
    assert count >= 1


@pytest.mark.parametrize(
    "path,required",
    [
        ("/models?free=1&tools=1", b"openrouter/free"),
        ("/models?harness=Hermes+Agent", b"GLM-5.3"),
        ("/models?q=GLM&provider=OpenRouter", b"via OpenRouter"),
        ("/models?context=1000000&tools=1", b"GLM-5.3"),
        ("/compatibility?harness=OpenCode&mcp=1", b"Compatible"),
        ("/compare?ids=1,2", b"Input / M"),
        ("/calculator?input_tokens=1000000&output_tokens=250000", b"/month"),
    ],
)
def test_finder_workflows_and_shared_filter_urls(client, path, required):
    response = client.get(path)
    assert response.status_code == 200
    assert required in response.data


@pytest.mark.parametrize(
    "query,expected",
    [
        ("free tools", {"free": "1", "tools": "1"}),
        ("deepseek coding", {"q": "deepseek", "use_case": "coding"}),
        ("openrouter 1m context", {"access": "openrouter", "context": "1000000"}),
        ("works with hermes", {"harness": "Hermes Agent"}),
        ("glm cheap coding", {"q": "glm", "sort": "weighted_cost", "use_case": "coding"}),
        ("open source tools", {"open_weights": "1", "tools": "1"}),
        ("image to 3d", {"type": "3D generation", "image_to_3d": "1"}),
        ("newest models this month", {"release": "month", "sort": "newest"}),
    ],
)
def test_deterministic_quick_search(query, expected):
    interpreted, labels = interpret_search({"q": query})
    assert labels
    for key, value in expected.items():
        assert interpreted[key] == value


def test_free_route_discloses_exact_provider_endpoint_and_caveats(client):
    response = client.get("/models?q=free+tools")
    assert response.status_code == 200
    assert b"OpenRouter" in response.data
    assert b"openrouter/free" in response.data
    assert b"Tools: Yes" in response.data
    assert b"200,000" in response.data
    assert b"50 requests/day" in response.data
    assert b"Last verified: 2026-09-29" in response.data


def test_media_routes_keep_native_pricing_units_and_features(client):
    response = client.get("/models?q=3d")
    assert response.status_code == 200
    assert b"Hunyuan 3D 3.1" in response.data
    assert b"per 3d generation" in response.data
    detail = client.get("/models/11", follow_redirects=True)
    assert detail.status_code == 200
    assert b"Media capabilities" in detail.data
    assert b"text to 3d" in detail.data


def test_offers_rankings_and_personal_setup_are_visible(client):
    assert client.get("/offers").status_code == 301
    offers = client.get("/deals")
    assert b"OpenRouter Free Models Router" in offers.data
    assert b"OpenAI Batch API" in offers.data
    assert b"First seen" in offers.data and b"Last verified" in offers.data
    rankings = client.get("/rankings")
    assert b"0.70" in rankings.data and b"Lowest estimated token cost for coding routes" in rankings.data
    assert b"no hidden universal" in rankings.data
    setup = client.get("/my-setup")
    assert b"Hermes Agent" in setup.data and b"OpenCode" in setup.data
    assert b"no API keys are stored" in setup.data


def test_price_history_preserves_previous_observation(app, client):
    with app.app_context():
        db = get_db()
        offering = db.execute("SELECT id FROM provider_offerings WHERE api_model_id='glm-5.3'").fetchone()[0]
        current = db.execute("SELECT id FROM pricing_records WHERE offering_id=? AND price_type='INPUT' AND valid_until IS NULL ORDER BY id DESC LIMIT 1", (offering,)).fetchone()[0]
        db.execute("UPDATE pricing_records SET valid_until='2026-09-28' WHERE id=?", (current,))
        db.execute("INSERT INTO pricing_records(offering_id,price_type,amount,valid_from) VALUES(?,?,?,?)", (offering, "INPUT", 1.20, "2026-09-28"))
        db.commit()
        summary = next(item for item in price_history(db, offering) if item["price_type"] == "INPUT")
        assert summary["previous"] == 1.4
        assert summary["current"] == 1.2
        assert summary["change_percent"] < 0
    response = client.get(f"/routes/{offering}", follow_redirects=True)
    assert b"Lowest observed" in response.data
    assert b"All observations (2)" in response.data


def test_multi_harness_setup_requires_compatibility_with_every_harness(client):
    response = client.get("/models?harnesses=Hermes+Agent,OpenCode&tools=1&sort=value")
    assert response.status_code == 200
    assert b"Hermes Agent:" in response.data
    assert b"OpenCode:" in response.data


def test_malformed_numeric_filters_do_not_error(client):
    response = client.get("/models?context=nope&input_max=not-a-price")
    assert response.status_code == 200
    assert b"Filter issue" in response.data
    api = client.get("/api/v1/search?context=nope")
    assert api.status_code == 200 and api.json["meta"]["warnings"]


@pytest.mark.parametrize("value", ["1M", "1M+", "1000000", "1,000,000", "1000K"])
def test_context_filter_friendly_forms_normalize(value):
    from app.query import normalize_context
    assert normalize_context(value) == 1_000_000


def test_harness_slug_and_display_name_share_compatibility_results(client):
    slug = client.get("/api/v1/search?harness=hermes-agent&limit=4").json["data"]
    display = client.get("/api/v1/search?harness=Hermes+Agent&limit=4").json["data"]
    assert [r["id"] for r in slug] == [r["id"] for r in display]


def test_subscription_included_zero_price_is_not_free(app, client):
    with app.app_context():
        db = get_db()
        from app.data_snapshot import apply_snapshot
        apply_snapshot(db, Path(__file__).resolve().parents[1] / "data" / "catalog.json")
        row = db.execute("SELECT id FROM provider_offerings WHERE access_semantics='INCLUDED_WITH_SUBSCRIPTION' LIMIT 1").fetchone()
        assert row is not None
        stored = db.execute("SELECT access_semantics,free_status FROM provider_offerings WHERE id=?", (row["id"],)).fetchone()
        assert tuple(stored) == ("INCLUDED_WITH_SUBSCRIPTION", "PAID")
        free_ids = {r["offering_id"] for r in route_rows(db, {"free":"1", "tools":"1", "limit":100000})}
        included_ids = {r["offering_id"] for r in route_rows(db, {"included":"1", "limit":100000})}
        assert row["id"] not in free_ids
        assert row["id"] in included_ids
    response = client.get("/api/v1/search?free=true&tools=true&limit=250")
    assert all(r["access_semantics"] != "INCLUDED_WITH_SUBSCRIPTION" for r in response.json["data"])


def test_weighted_cost_sort_uses_visible_formula(app):
    with app.app_context():
        rows = [row for row in route_rows(get_db(), {"tools": "1", "sort": "weighted_cost"}) if row["weighted_cost"] is not None]
    assert rows == sorted(rows, key=lambda row: row["weighted_cost"])


def test_public_api_contract_and_filters(client):
    response = client.get("/api/v1/models?tools=true&max_output_price=1&harness=hermes-agent")
    assert response.status_code == 200
    assert response.json["meta"]["api_version"] == "v1"
    assert all(route["capabilities"]["tools"] == "YES"
               for model in response.json["data"] for route in model["routes"])
    search = client.get("/api/v1/search?type=3d")
    assert search.status_code == 200
    assert all(item["model"]["type"] == "3D generation" for item in search.json["data"])
    assert client.post("/api/v1/models").status_code == 405


def test_api_applies_harness_compatibility_before_result_limit(client):
    response = client.get("/api/v1/search?q=cheap+tools&harness=hermes&limit=1")
    assert response.status_code == 200
    assert response.json["meta"]["count"] == 1
    assert response.json["data"][0]["compatibility"]["status"] in {
        "COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION", "PARTIAL"}

    compatibility = client.get("/api/v1/compatibility?harness=hermes&limit=1")
    assert compatibility.status_code == 200
    assert compatibility.json["meta"]["harness"]["slug"] == "hermes-agent"


def test_public_api_resources_and_slug_detail(client):
    for path in ["/api/v1", "/api/v1/providers", "/api/v1/harnesses", "/api/v1/offers",
                 "/api/v1/releases", "/api/v1/benchmarks"]:
        response = client.get(path)
        assert response.status_code == 200
        assert "data" in response.json and "meta" in response.json
    detail = client.get("/api/v1/models/zhipuai/glm-5.3")
    assert detail.status_code == 200
    assert detail.json["data"]["slug"] == "zhipuai/glm-5.3"


def test_seo_discovery_and_filter_index_policy(client):
    assert client.get("/robots.txt").status_code == 200
    assert b"Sitemap:" in client.get("/robots.txt").data
    assert b"<sitemapindex" in client.get("/sitemap.xml").data
    assert b"<urlset" in client.get("/sitemaps/models.xml").data
    assert client.get("/feeds/releases.atom").mimetype == "application/atom+xml"
    assert client.get("/feeds/price-changes.atom").mimetype == "application/atom+xml"
    assert client.get("/feeds/deals.atom").mimetype == "application/atom+xml"
    assert client.get("/feeds/changes.json").json["version"].endswith("1.1")
    filtered = client.get("/models?tools=1")
    assert b'name="robots" content="noindex,follow"' in filtered.data
    assert b'rel="canonical"' in filtered.data


def test_machine_discovery_endpoints_and_canonical_origin(app):
    app.config["PUBLIC_BASE_URL"] = "https://usethismodel.com"
    client = app.test_client()
    home = client.get("/", headers={"Host": "untrusted.example"})
    assert b'<link rel="canonical" href="https://usethismodel.com/">' in home.data
    robots = client.get("/robots.txt")
    assert b"Sitemap: https://usethismodel.com/sitemap.xml" in robots.data
    sitemap = client.get("/sitemap.xml")
    assert b"http://usethismodel.com" not in sitemap.data
    assert b"usethismodel.codefiction.net" not in sitemap.data
    assert b"https://usethismodel.com/sitemaps/core.xml" in sitemap.data
    llms = client.get("/llms.txt")
    assert llms.status_code == 200
    assert llms.mimetype == "text/plain"
    assert b"Public API documentation: https://usethismodel.com/api" in llms.data
    api_docs = client.get("/api")
    assert b'<link rel=canonical href="https://usethismodel.com/api">' in api_docs.data
    spec = client.get("/api/v1/openapi.json").json
    assert spec["openapi"] == "3.1.0"
    assert spec["servers"] == [{"url": "https://usethismodel.com"}]
    assert "/api/v1/models" in spec["paths"]
    assert "/api/v1/models/{slug}" in spec["paths"]


def test_canonical_host_redirect_preserves_path_and_query(client):
    response = client.get("/models/glm-5-3?tools=true", headers={"Host": "usethismodel.codefiction.net"})
    assert response.status_code == 308
    assert response.headers["Location"] == "https://usethismodel.com/models/glm-5-3?tools=true"


@pytest.mark.parametrize("path", ["/", "/models", "/providers", "/harnesses", "/deals", "/releases", "/benchmarks", "/models/glm-5-3", "/providers/openrouter", "/harnesses/opencode", "/workflows/unreal-engine"])
def test_representative_pages_use_canonical_origin_and_are_indexable(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert b"https://usethismodel.com" in response.data
    assert b"usethismodel.codefiction.net" not in response.data
    assert b'<meta name="robots" content="noindex' not in response.data


@pytest.mark.parametrize("path,needle", [
    ("/models/glm-5-3", b"GLM-5.3"),
    ("/providers/openrouter", b"OpenRouter"),
    ("/providers/z-ai", b"Z.ai"),
    ("/harnesses/opencode", b"OpenCode"),
    ("/harnesses/hermes", b"Hermes Agent"),
    ("/harnesses/pi", b"Pi providers"),
    ("/harnesses/codex", b"Codex CLI"),
    ("/use-cases/free-tool-calling", b"Current provider routes"),
    ("/use-cases/agentic-coding", b"Relevant benchmark observations"),
    ("/use-cases/long-context", b"Last verified"),
    ("/use-cases/3d-generation", b"3D"),
    ("/deals", b"Offers &amp; deals"),
    ("/releases", b"New releases"),
])
def test_public_discovery_pages_are_stable_and_factual(client, path, needle):
    response = client.get(path, headers={"User-Agent": "pytest crawler"})
    assert response.status_code == 200
    assert needle in response.data
    assert b'application/ld+json' in response.data or path.startswith(("/providers/", "/harnesses/"))


def test_crawler_policy_separates_search_from_training_and_internal_pages(client):
    robots = client.get("/robots.txt").data
    search_group = robots.split(b"User-agent: Googlebot", 1)[1].split(b"User-agent: GPTBot", 1)[0]
    assert b"User-agent: OAI-SearchBot" in search_group
    assert b"Allow: /" in search_group
    assert b"Disallow: /internal/" in search_group
    assert b"Disallow: /*?" in search_group
    assert b"User-agent: GPTBot\nDisallow: /" in robots
    assert b"Disallow: /internal/" in robots
    assert client.get("/internal/data-quality").status_code == 404


def test_analytics_are_aggregate_and_do_not_store_search_text(client, app):
    client.get("/models?q=a-sensitive-query", headers={"User-Agent": "Mozilla/5.0"})
    client.post("/analytics/event", json={"event": "deal_click", "provider": "OpenRouter"})
    with app.app_context():
        records = get_db().execute("SELECT event,dimension,count FROM analytics_daily ORDER BY event").fetchall()
    assert [(row["event"], row["dimension"]) for row in records] == [
        ("deal_click", "openrouter"), ("search", "models")]
    assert "sensitive" not in str([tuple(row) for row in records])


def test_search_keeps_model_punctuation_and_keyword_boundaries(client):
    assert b"GLM-5.3" in client.get("/models?q=glm-5.3").data
    assert b"GLM-5.3" in client.get("/models?q=glm+5.3").data
    interpreted, _ = interpret_search({"q": "notopenrouterish"})
    assert "access" not in interpreted
    assert client.get("/api/v1/free-routes?tools=true").status_code == 200


def test_product_audit_default_view_is_bounded_and_decision_first(client):
    response = client.get("/models")
    assert response.status_code == 200
    assert response.data.count(b'class="route-card"') == 18
    assert b"Useful starting points" in response.data
    assert b"max output price" in response.data
    assert b"Required capabilities" in response.data
    assert b"Next" in response.data
    assert response.data.index(b"Required capabilities") < response.data.index(b"Advanced filters")


@pytest.mark.parametrize(
    "query,required",
    [
        ("unreal", b"Workflow: Unreal"),
        ("reaper mcp", b"Workflow: Reaper"),
        ("deals right now", b"Active deal"),
        ("new models this week", b"Release: this week"),
        ("3d", b"Category: 3D generation"),
    ],
)
def test_product_language_search_is_forgiving(client, query, required):
    response = client.get("/models", query_string={"q": query})
    assert response.status_code == 200
    assert required in response.data


def test_my_setup_and_compare_are_route_specific_and_bounded(client):
    setup = client.get("/my-setup?harnesses=OpenCode&workflows=unreal-engine")
    assert setup.status_code == 200
    assert b"Good choices for your setup" in setup.data
    assert b"EXPLICIT MATCHING RULES" in setup.data
    assert 1 <= setup.data.count(b'class="route-card"') <= 6

    compare = client.get("/compare?q=GLM+5.3+with+DeepSeek")
    assert compare.status_code == 200
    assert b"GLM-5.3" in compare.data
    assert b"DeepSeek" in compare.data
    assert b"EXACT PROVIDER ROUTES" in compare.data


def test_dense_decision_pages_limit_initial_rendering(client):
    compatibility = client.get(
        "/compatibility?workflow=unreal-engine&harness=OpenCode&tools=1&mcp=1"
    )
    assert compatibility.data.count(b'class="route-card"') <= 12
    calculator = client.get("/calculator")
    assert calculator.data.count(b'class="route-card"') <= 12
    detail = client.get("/models/zhipuai/glm-5.3")
    assert 1 <= detail.data.count(b'class="route-card"') <= 12
    models = client.get("/models").data
    assert all(label in models for label in (b"MODEL", b"PROVIDER ROUTE", b"PRICE", b"HARNESS FIT"))


@pytest.mark.parametrize("path", [
    "/models?offering_id=nope", "/models?model_id=nope", "/models?provider_id=nope",
    "/calculator?input_tokens=nope&output_tokens=-5&cache_share=what",
])
def test_malformed_public_numeric_inputs_do_not_error(client, path):
    assert client.get(path).status_code == 200


def test_public_api_caps_requested_route_page(client):
    response = client.get('/api/v1/search?limit=100000&query=')
    assert response.status_code == 200
    assert response.json['meta']['count'] <= 250
    assert response.headers['Cache-Control'].startswith('public, max-age=60')


def test_rest_pagination_contract_enumerates_complete_model_catalog(client, app):
    first = client.get('/api/v1/models?limit=5&page=1').json
    second = client.get('/api/v1/models?limit=5&page=2').json
    assert first['meta']['count'] == 5
    assert first['meta']['total'] > 5
    assert first['meta']['offset'] == 0
    assert first['meta']['next_offset'] == 5
    assert first['meta']['has_more'] is True
    assert second['meta']['offset'] == 5
    assert second['meta']['previous_offset'] == 0
    assert not ({row['id'] for row in first['data']} & {row['id'] for row in second['data']})
    with app.app_context():
        total_models = get_db().execute('SELECT COUNT(*) FROM models').fetchone()[0]
    assert first['meta']['total'] == total_models
    offset_page = client.get('/api/v1/models?limit=5&offset=5').json
    assert [x['id'] for x in offset_page['data']] == [x['id'] for x in second['data']]


@pytest.mark.parametrize('path', [
    '/api/v1/providers', '/api/v1/harnesses', '/api/v1/offers', '/api/v1/plans',
    '/api/v1/workflows', '/api/v1/benchmarks', '/api/v1/access-routes',
    '/api/v1/releases?window=all', '/api/v1/search',
])
def test_api_collections_expose_total_and_next_page(client, path):
    response = client.get(path + ('&' if '?' in path else '?') + 'limit=3&offset=0')
    assert response.status_code == 200
    meta = response.json['meta']
    assert meta['count'] == min(3, meta['total'])
    assert meta['limit'] == 3
    assert meta['offset'] == 0
    assert meta['next_offset'] == (3 if meta['total'] > 3 else None)
    assert meta['has_more'] is (meta['total'] > 3)


def test_releases_api_defaults_to_full_enumerable_catalog(client):
    default = client.get('/api/v1/releases?limit=3').json
    all_releases = client.get('/api/v1/releases?window=all&limit=3').json
    recent = client.get('/api/v1/releases?window=7-days&limit=3').json
    assert default['meta']['total'] == all_releases['meta']['total']
    assert default['meta']['window'] == 'all'
    assert recent['meta']['total'] <= all_releases['meta']['total']


def test_gpt_6_1_sol_has_official_release_and_route_evidence(app):
    from app.data_snapshot import apply_snapshot
    with app.app_context():
        db = get_db()
        apply_snapshot(db, Path(__file__).parents[1] / 'data/catalog.json')
        row = db.execute("""SELECT m.canonical_name,m.released_at,m.release_date_kind,
          o.api_model_id,o.context_limit,o.max_output_tokens,o.tool_support,s.url
          FROM models m JOIN provider_offerings o ON o.model_id=m.id
          JOIN sources s ON s.id=o.source_id WHERE o.api_model_id='gpt-6.1-sol'""").fetchone()
        prices = {r['price_type']: r['amount'] for r in db.execute("""SELECT price_type,amount
          FROM pricing_records p JOIN provider_offerings o ON o.id=p.offering_id
          WHERE o.api_model_id='gpt-6.1-sol' AND p.valid_until IS NULL""")}
    assert row['canonical_name'] == 'GPT-6.1 Sol'
    assert (row['released_at'], row['release_date_kind']) == ('2026-09-29', 'official')
    assert row['url'] == 'https://developers.openai.com/api/docs/models/gpt-6.1-sol'
    assert (row['context_limit'], row['max_output_tokens'], row['tool_support']) == (1050000, 128000, 'YES')
    assert prices == {'INPUT': 2, 'CACHE_READ': 0.1, 'CACHE_WRITE': 2.5, 'OUTPUT': 10}


def test_invalid_pagination_is_rejected_and_large_limit_is_capped(client):
    assert client.get('/api/v1/models?page=0').status_code == 400
    assert client.get('/api/v1/models?page=2&offset=20').status_code == 400
    assert client.get('/api/v1/models?limit=100000').json['meta']['limit'] == 250


def test_free_route_api_applies_provider_and_access_semantics(client):
    response = client.get('/api/v1/free-routes?provider=OpenRouter&limit=20')
    assert response.status_code == 200
    assert response.json['meta']['total'] > 0
    assert all(row['provider']['name'] == 'OpenRouter' for row in response.json['data'])
    assert all(row['access_semantics'] in {'FREE_API','FREE_TIER','PROMOTIONAL_FREE','TRIAL_CREDIT'} for row in response.json['data'])
    assert client.get('/api/v1/free-routes?provider=not-a-provider').status_code == 400


@pytest.mark.parametrize('phrase,expected', [
    ('codex', 'Codex CLI'), ('codex cli', 'Codex CLI'), ('claude code', 'Claude Code'),
    ('open code', 'OpenCode'), ('hermes-agent', 'Hermes Agent'), ('gemini cli', 'Gemini CLI'),
    ('qwen code', 'Qwen Code'), ('goose', 'Goose'), ('cline', 'Cline'), ('roo code', 'Roo Code'),
    ('aider', 'Aider'), ('continue', 'Continue'), ('zcode', 'ZCode'), ('zed', 'Zed'),
    ('junie cli', 'Junie CLI'), ('cursor cli', 'Cursor CLI'), ('amp', 'Amp'), ('droid', 'Factory Droid'),
])
def test_registered_harnesses_and_aliases_are_deterministically_searchable(phrase, expected):
    filters, applied = interpret_search({'q': f'works with {phrase}'})
    assert filters['harness'] == expected
    assert any(label == f'Harness: {expected}' for label in applied)


def test_harness_slug_and_display_name_resolve_identically(client):
    slug = client.get('/api/v1/compatibility?harness=hermes-agent&limit=5').json
    display = client.get('/api/v1/compatibility?harness=Hermes%20Agent&limit=5').json
    assert slug['meta']['harness'] == display['meta']['harness']
    assert [r['id'] for r in slug['data']] == [r['id'] for r in display['data']]


def test_modality_taxonomy_preserves_source_modality(client):
    from app.query import modality_category
    assert modality_category('text,image', 'FLUX.2 [pro]') == 'Image generation'
    assert modality_category('audio->text', 'Whisper') == 'Speech-to-text'
    assert modality_category('text,audio', 'ChatGPT') == 'Multimodal LLM'
    assert modality_category('unknown-format', 'Unknown') == 'Other'
    response = client.get('/api/v1/search?limit=20')
    assert response.status_code == 200
    assert all(row['model']['modality_category'] == row['model']['type'] for row in response.json['data'])
    assert all(row['model']['raw_modality'] for row in response.json['data'])
    with client.application.app_context():
        from app.query import filter_options
        assert len(filter_options(get_db())['types']) <= 10


def test_releases_page_is_chronological_and_labels_date_provenance(client):
    response = client.get('/releases')
    assert response.status_code == 200
    body = response.data.decode()
    assert 'Official date' in body or 'Aggregator date' in body or 'Publisher metadata date' in body or 'Unverified date' in body
    import re
    dates = re.findall(r'Released (\d{4}-\d{2}-\d{2})', body)
    assert dates == sorted(dates, reverse=True)
    assert 'route' in body.lower()


def test_offers_page_exposes_catalog_pagination_and_filters(client):
    with client.application.app_context():
        db = get_db()
        from app.data_snapshot import apply_snapshot
        apply_snapshot(db, Path(__file__).parents[1] / 'data/catalog.json')
    first = client.get('/deals?page=1')
    assert first.status_code == 200
    assert b'current offers in the catalog' in first.data
    assert b'Next' in first.data
    provider = client.application.test_client().get('/api/v1/offers?limit=1').json['data'][0]['provider_name']
    filtered = client.get('/deals?provider=' + provider.replace(' ', '+'))
    assert filtered.status_code == 200
    assert provider.encode() in filtered.data
    assert b'name="harness"' in filtered.data and b'name="context"' in filtered.data


def test_llms_full_is_current_conditional_and_sitemap_lastmod_is_valid(client):
    with client.application.app_context():
        from app.data_snapshot import apply_snapshot
        apply_snapshot(get_db(), Path(__file__).parents[1] / 'data/catalog.json')
    response = client.get('/llms-full.txt')
    assert response.status_code == 200
    assert b'## Models with the broadest current route coverage' in response.data
    assert b'## Harnesses' in response.data and b'## Current offers' in response.data
    assert response.headers.get('ETag')
    assert client.get('/llms-full.txt', headers={'If-None-Match': response.headers['ETag']}).status_code == 304
    changes = client.get('/feeds/changes.json')
    assert changes.headers.get('ETag')
    assert client.get('/feeds/changes.json', headers={'If-None-Match': changes.headers['ETag']}).status_code == 304
    sitemap = client.get('/sitemaps/models.xml')
    parsed = ElementTree.fromstring(sitemap.data)
    ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    dates = [node.text for node in parsed.findall('.//s:lastmod', ns)]
    assert dates and all(re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) for value in dates)
    assert sitemap.headers.get('ETag')


def test_old_public_paths_redirect_to_canonical_navigation(client):
    assert client.get('/offers').headers['Location'].endswith('/deals')
    assert client.get('/new-releases').headers['Location'].endswith('/releases')
    home = client.get('/').data
    assert b'href="/offers"' not in home
    assert b'href="/new-releases"' not in home

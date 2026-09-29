import sqlite3

import pytest

from app import create_app
from app.db import get_db
from app.domain import canonical_model, compatibility_for
from app.query import interpret_search, price_history, route_rows


@pytest.fixture()
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3")})


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

    assert migrations == [(1,), (2,), (3,), (4,), (5,), (6,), (7,), (8,), (9,)]
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
    } <= tables


def test_health_checks_sqlite(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok", "database": "sqlite"}


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/models",
        "/providers",
        "/harnesses",
        "/compatibility",
        "/offers",
        "/new-releases",
        "/benchmarks",
        "/use-cases",
        "/compare",
        "/calculator",
        "/rankings",
        "/my-setup",
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


def test_catalog_detail_pages(client):
    for path in ["/models/1", "/providers/1", "/harnesses/1"]:
        response = client.get(path)
        assert response.status_code == 301
        assert client.get(response.location).status_code == 200


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
        ("glm cheap coding", {"q": "glm", "sort": "value", "use_case": "coding"}),
        ("open source tools", {"open_weights": "1", "tools": "1"}),
        ("image to 3d", {"type": "3D generation", "image_to_3d": "1"}),
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
    offers = client.get("/offers")
    assert b"OpenRouter Free Models Router" in offers.data
    assert b"OpenAI Batch API" in offers.data
    assert b"First seen" in offers.data and b"Last verified" in offers.data
    rankings = client.get("/rankings")
    assert b"0.70" in rankings.data and b"Best-value coding" in rankings.data
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


def test_value_sort_uses_visible_formula(app):
    with app.app_context():
        rows = [row for row in route_rows(get_db(), {"tools": "1", "sort": "value"}) if row["value_score"] is not None]
    assert rows == sorted(rows, key=lambda row: row["value_score"])


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
    assert b"<urlset" in client.get("/sitemap.xml").data
    assert client.get("/feeds/releases.atom").mimetype == "application/atom+xml"
    assert client.get("/feeds/price-changes.atom").mimetype == "application/atom+xml"
    filtered = client.get("/models?tools=1")
    assert b'name="robots" content="noindex,follow"' in filtered.data
    assert b'rel="canonical"' in filtered.data


def test_search_keeps_model_punctuation_and_keyword_boundaries(client):
    assert b"GLM-5.3" in client.get("/models?q=glm-5.3").data
    interpreted, _ = interpret_search({"q": "notopenrouterish"})
    assert "access" not in interpreted


@pytest.mark.parametrize("path", [
    "/models?offering_id=nope", "/models?model_id=nope", "/models?provider_id=nope",
    "/calculator?input_tokens=nope&output_tokens=-5&cache_share=what",
])
def test_malformed_public_numeric_inputs_do_not_error(client, path):
    assert client.get(path).status_code == 200

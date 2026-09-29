import sqlite3

import pytest

from app import create_app
from app.db import get_db
from app.domain import canonical_model, compatibility_for


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

    assert migrations == [(1,), (2,), (3,), (4,), (5,), (6,), (7,)]
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
        assert client.get(path).status_code == 200


@pytest.mark.parametrize(
    "path,required",
    [
        ("/models?free=1&tools=1", b"No routes match"),
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

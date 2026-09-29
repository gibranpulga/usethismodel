import sqlite3

import pytest

from app import create_app


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

    assert migrations == [(1,), (2,)]
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

import pytest

from app import create_app
from app.benchmark_sources import BENCHMARK_REGISTRY, sync_benchmark_registry
from app.db import get_db

NOW = "2026-09-29T12:00:00+00:00"
LATER = "2026-09-30T12:00:00+00:00"


@pytest.fixture
def db(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "benchmarks.sqlite3")})
    with app.app_context():
        connection = get_db()
        columns = {row[1] for row in connection.execute("PRAGMA table_info(benchmarks)")}
        additions = {
            "is_current": "INTEGER NOT NULL DEFAULT 0",
            "last_verified_at": "TEXT",
            "published_at": "TEXT",
            "methodology_url": "TEXT",
            "task_count": "INTEGER",
        }
        for name, declaration in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE benchmarks ADD COLUMN {name} {declaration}")
        connection.commit()
        yield connection


def test_sync_registers_only_publisher_metadata(db):
    result_count = db.execute("SELECT COUNT(*) FROM benchmark_results").fetchone()[0]

    assert sync_benchmark_registry(db, NOW) == 6

    rows = db.execute(
        """SELECT b.name,b.version,b.category,b.is_current,b.last_verified_at,
                  b.published_at,b.methodology_url,b.task_count,
                  s.url,s.source_type,s.reliability
             FROM benchmarks b JOIN sources s ON s.id=b.source_id
            WHERE b.is_current=1 ORDER BY b.name"""
    ).fetchall()
    assert {(row["name"], row["version"]) for row in rows} == {
        (entry.name, entry.version) for entry in BENCHMARK_REGISTRY
    }
    assert all(row["last_verified_at"] == NOW for row in rows)
    assert all(row["methodology_url"].startswith("https://") for row in rows)
    assert all(row["url"].startswith("https://") for row in rows)
    assert all(row["source_type"] == "benchmark_publisher" for row in rows)
    assert all(row["reliability"] == "HIGH" for row in rows)
    assert db.execute("SELECT COUNT(*) FROM benchmark_results").fetchone()[0] == result_count


def test_sync_is_repeatable_and_preserves_superseded_versions(db):
    source_id = db.execute("SELECT id FROM sources ORDER BY id LIMIT 1").fetchone()[0]
    db.execute(
        """UPDATE benchmarks
              SET category=?,description=?,source_id=?,is_current=1,last_verified_at=?
            WHERE name=? AND version=?""",
        (
            "Agentic coding",
            "Historical description",
            source_id,
            "2025-01-01T00:00:00+00:00",
            "Terminal-Bench",
            "2.0",
        ),
    )
    db.commit()

    sync_benchmark_registry(db, NOW)
    sync_benchmark_registry(db, LATER)

    versions = db.execute(
        """SELECT version,description,is_current,last_verified_at
             FROM benchmarks WHERE name='Terminal-Bench' ORDER BY version"""
    ).fetchall()
    assert [row["version"] for row in versions] == ["2.0", "4.0.0"]
    historical = versions[0]
    assert dict(historical) == {
        "version": "2.0",
        "description": "Historical description",
        "is_current": 0,
        "last_verified_at": "2025-01-01T00:00:00+00:00",
    }
    current = versions[-1]
    assert current["is_current"] == 1
    assert current["last_verified_at"] == LATER
    assert db.execute(
        "SELECT COUNT(*) FROM benchmarks WHERE name='Terminal-Bench' AND version='4.0.0'"
    ).fetchone()[0] == 1

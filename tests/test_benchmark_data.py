from contextlib import contextmanager

from app import create_app
from app.benchmark_import import import_publisher_results
from app.benchmark_queries import comparable_groups
from app.benchmark_sources import sync_benchmark_registry, sync_publisher_results
from app.data_snapshot import apply_snapshot
from app.db import get_db
from app.query import ranking_groups

NOW = "2026-09-30T12:00:00+00:00"


@contextmanager
def seeded_db(tmp_path, snapshot=False):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "benchmark.sqlite3"),
                      "APPLY_DATA_SNAPSHOT": False})
    with app.app_context():
        db = get_db()
        if snapshot:
            apply_snapshot(db, "data/catalog.json")
        else:
            db.executemany("INSERT INTO models(canonical_name,vendor,canonical_slug) VALUES(?,?,?)", [
                ("Fixture Model A", "Fixture", "fixture/model-a"),
                ("Fixture Model B", "Fixture", "fixture/model-b"),
            ])
        sync_benchmark_registry(db, NOW)
        yield app, db


def record(db, model_id, benchmark="Terminal-Bench", version="4.0.0", **overrides):
    source_url = overrides.pop("source_url", "https://publisher.example/results.json")
    db.execute("""INSERT INTO sources(name,url,source_type,fetched_at,reliability)
        VALUES('Publisher results',?,'benchmark_publisher',?,'HIGH')
        ON CONFLICT(url) DO NOTHING""", (source_url, NOW))
    result = {
        "benchmark_name": benchmark, "benchmark_version": version,
        "model_id": model_id, "model_version": "publisher-model-id",
        "score": 52.5, "metric": "accuracy (%)", "task_subset": "full dataset",
        "harness_name": "Example Agent", "harness_version": "1.2.3", "scaffold": "example-agent",
        "reasoning_setting": "high", "attempts_per_task": 5,
        "evaluated_at": "2026-09-01", "source_url": source_url, "confidence": "HIGH",
    }
    result.update(overrides)
    return result


def test_import_is_idempotent_and_changed_scores_are_reviewed(tmp_path):
    with seeded_db(tmp_path) as (app, db):
        model_id = db.execute("SELECT id FROM models ORDER BY id LIMIT 1").fetchone()[0]
        entry = record(db, model_id)
        assert import_publisher_results(db, [entry]) == 1
        assert import_publisher_results(db, [entry]) == 0
        changed = {**entry, "score": 53.0}
        assert import_publisher_results(db, [changed]) == 0
        assert db.execute("SELECT score FROM benchmark_results WHERE model_id=? AND metric='accuracy (%)'", (model_id,)).fetchone()[0] == 52.5
        review = db.execute("SELECT reason FROM review_queue WHERE proposed_change='publisher_score_correction'").fetchone()
        assert review and "previous result retained" in review[0]


def test_comparisons_scope_benchmark_version_and_exact_run_configuration():
    base = {"benchmark_id": 1, "benchmark": "Terminal-Bench", "version": "4.0.0",
            "metric": "accuracy (%)", "task_subset": "full", "harness_name": "Agent",
            "scaffold": "agent", "model_id": 1, "model": "A", "score": 80}
    second = {**base, "model_id": 2, "model": "B", "score": 70}
    rows = [base, second,
            {**second, "benchmark_id": 2, "version": "5.0"},
            {**second, "scaffold": "different-agent"},
            {**second, "harness_name": None, "scaffold": None, "task_subset": None}]
    groups = comparable_groups(rows)
    assert len(groups) == 1
    assert {row["model_id"] for row in groups[0]["results"]} == {1, 2}
    assert groups[0]["version"] == "4.0.0"


def test_source_failure_keeps_previous_valid_rows_and_creates_review(tmp_path, monkeypatch):
    import app.benchmark_sources as sources

    with seeded_db(tmp_path) as (app, db):
        model_id = db.execute("SELECT id FROM models ORDER BY id LIMIT 1").fetchone()[0]
        import_publisher_results(db, [record(db, model_id)])
        before = db.execute("SELECT COUNT(*) FROM benchmark_results").fetchone()[0]
        monkeypatch.setattr(sources, "_livebench_records", lambda *_: (_ for _ in ()).throw(ValueError("schema changed")))
        monkeypatch.setattr(sources, "_terminal_records", lambda *_: (_ for _ in ()).throw(OSError("offline")))
        monkeypatch.setattr(sources, "_swe_verified_records", lambda *_: (_ for _ in ()).throw(OSError("offline")))
        result = sync_publisher_results(db, NOW)
        assert len(result["failures"]) == 3
        assert db.execute("SELECT COUNT(*) FROM benchmark_results").fetchone()[0] == before
        assert db.execute("SELECT COUNT(*) FROM review_queue WHERE entity LIKE 'benchmark_source:%'").fetchone()[0] == 3


def test_partial_publisher_import_rolls_back_all_rows_for_that_source(tmp_path, monkeypatch):
    import app.benchmark_sources as sources

    with seeded_db(tmp_path) as (app, db):
        model_id = db.execute("SELECT id FROM models ORDER BY id LIMIT 1").fetchone()[0]
        before = db.execute("SELECT COUNT(*) FROM benchmark_results").fetchone()[0]
        valid = record(db, model_id, benchmark="LiveBench", version="2026-06-25",
                       task_subset="code_generation", source_url="https://publisher.example/live.csv")
        invalid = record(db, model_id, benchmark="Unregistered version",
                         source_url="https://publisher.example/changed.json")
        monkeypatch.setattr(sources, "_livebench_records", lambda *_: ([valid, invalid], []))
        monkeypatch.setattr(sources, "_terminal_records", lambda *_: ([], []))
        monkeypatch.setattr(sources, "_swe_verified_records", lambda *_: ([], []))
        result = sync_publisher_results(db, NOW)
        assert result["inserted"] == 0
        assert len(result["failures"]) == 1
        assert db.execute("SELECT COUNT(*) FROM benchmark_results").fetchone()[0] == before


def test_api_and_mcp_return_source_configuration_and_shared_comparisons(tmp_path):
    with seeded_db(tmp_path) as (app, db):
        models = db.execute("SELECT id,canonical_slug FROM models ORDER BY id LIMIT 2").fetchall()
        for model in models:
            import_publisher_results(db, [record(db, model["id"])])
        db.commit()
        response = app.test_client().get("/api/v1/benchmarks?benchmark=Terminal-Bench&version=4.0.0&current_only=true&compare=" + models[0]["canonical_slug"] + "," + models[1]["canonical_slug"])
        assert response.status_code == 200
        payload = response.get_json()["data"]
        result = payload[0]["results"][0]
        assert result["source_url"] == "https://publisher.example/results.json"
        assert result["scaffold"] == "example-agent"
        assert len(payload[0]["comparable_groups"]) == 1
        from app.mcp_server import bind_app, get_benchmarks
        bind_app(app)
        result = get_benchmarks(benchmark="Terminal-Bench", version="4.0.0",
                                compare_models=[models[0]["canonical_slug"], models[1]["canonical_slug"]])
        assert result["comparable_groups"]
        assert result["items"][0]["sources"][0]["url"] == "https://publisher.example/results.json"


def test_api_current_only_filters_historical_result_rows(tmp_path):
    with seeded_db(tmp_path, snapshot=True) as (app, db):
        response = app.test_client().get("/api/v1/benchmarks?current_only=true")
        assert response.status_code == 200
        payload = response.get_json()["data"]
        assert all(item["is_current"] for item in payload)
        assert all(not (item["name"] == "LiveBench" and item["version"] == "2025-02") for item in payload)


def test_rankings_never_make_a_cross_benchmark_score_list(tmp_path):
    with seeded_db(tmp_path) as (app, db):
        model_id = db.execute("SELECT id FROM models ORDER BY id LIMIT 1").fetchone()[0]
        first = record(db, model_id)
        second = record(db, model_id, benchmark="SWE-bench Verified", version="500-task subset",
                        metric="resolved (%)", source_url="https://publisher.example/swe.json")
        import_publisher_results(db, [first, second])
        groups = [group for group in ranking_groups(db) if group["kind"] == "benchmark"]
        assert not groups


def test_rankings_sort_only_inside_matching_benchmark_and_configuration(tmp_path):
    with seeded_db(tmp_path) as (app, db):
        models = db.execute("SELECT id FROM models ORDER BY id LIMIT 2").fetchall()
        low = record(db, models[0][0], score=61.0)
        high = record(db, models[1][0], score=72.0)
        other = record(db, models[1][0], benchmark="SWE-bench Verified",
                       version="500-task subset", metric="resolved (%)", score=98.0,
                       source_url="https://publisher.example/swe.json")
        import_publisher_results(db, [low, high, other])
        groups = [group for group in ranking_groups(db) if group["kind"] == "benchmark"]
        assert len(groups) == 1
        assert [row["score"] for row in groups[0]["rows"]] == [72.0, 61.0]
        assert groups[0]["title"].startswith("Terminal-Bench 4.0.0")


def test_compare_page_shows_only_shared_like_for_like_evidence(tmp_path):
    with seeded_db(tmp_path, snapshot=True) as (app, db):
        model_routes = db.execute("""SELECT o.id offering_id,m.id model_id FROM provider_offerings o
            JOIN models m ON m.id=o.model_id GROUP BY m.id ORDER BY m.id LIMIT 2""").fetchall()
        assert len(model_routes) == 2
        for item in model_routes:
            import_publisher_results(db, [record(db, item["model_id"])])
        db.commit()
        response = app.test_client().get(f"/compare?ids={model_routes[0]['offering_id']},{model_routes[1]['offering_id']}")
        assert response.status_code == 200
        assert b"Shared benchmark evidence" in response.data
        assert b"publisher.example/results.json" in response.data

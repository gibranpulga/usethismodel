"""Offline checks for catalog precedence, quarantine, and atomic deployment."""

import json

import pytest

from app import create_app
from app.data_snapshot import apply_snapshot, encode, snapshot
from app.data_update import priority, update, write_outputs
from app.db import get_db

NOW = "2026-09-20T12:00:00+00:00"
LATER = "2026-09-21T12:00:00+00:00"


@pytest.fixture
def db(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "catalog.sqlite3")})
    with app.app_context():
        yield get_db()


def record(source="models.dev", fields=None, api_id="verification-model", provider="verification", canonical=None):
    return {
        "source": source,
        "source_url": f"https://{source}.example.test/catalog",
        "source_kind": "fixture",
        "priority": -1000,  # Incoming precedence must never be trusted.
        "provider_key": provider,
        "provider_name": provider.title(),
        "api_model_id": api_id,
        "canonical_slug": canonical or f"{provider}/{api_id}",
        "name": api_id,
        "fields": fields if fields is not None else {"input_price": 2, "output_price": 6},
    }


def run(db, records, now=NOW, failures=None):
    with db:
        return update(db, records, failures or [], {}, now)


def route(db, api_id="verification-model", provider="Verification"):
    return db.execute(
        "SELECT o.* FROM provider_offerings o JOIN providers p ON p.id=o.provider_id "
        "WHERE p.name=? AND o.api_model_id=?", (provider, api_id),
    ).fetchone()


def prices(db, offering):
    return dict(db.execute(
        "SELECT price_type,amount FROM pricing_records WHERE offering_id=? AND valid_until IS NULL",
        (offering,),
    ).fetchall())


@pytest.mark.parametrize("missing", [{}, {"input_price": None, "output_price": None, "tool_calling": None}])
def test_missing_or_null_fields_retain_previous_facts(db, missing):
    run(db, [record(fields={"input_price": 2, "output_price": 6, "tool_calling": True})])
    before = route(db)
    report = run(db, [record(fields=missing)], LATER)
    assert prices(db, before["id"]) == {"INPUT": 2, "OUTPUT": 6}
    assert route(db)["tool_support"] == "YES"
    assert not report["Price reductions"]


def test_official_precedence_ignores_payload_priority_and_retains_disagreements(db):
    records = [record(source, {"input_price": value}) for source, value in [
        ("litellm", 40), ("models.dev", 30), ("openrouter", 20), ("official_provider", 10),
    ]]
    report = run(db, records)
    oid = route(db)["id"]
    assert prices(db, oid)["INPUT"] == 10
    selected = db.execute(
        "SELECT d.source,d.priority FROM selected_facts s JOIN data_observations d "
        "ON d.id=s.observation_id WHERE s.entity=? AND s.field='input_price'", (f"offering:{oid}",),
    ).fetchone()
    assert tuple(selected) == ("official_provider", 10)
    assert len([r for r in report["Conflicts"] if r["entity"] == f"offering:{oid}"]) == 3
    run(db, [record("litellm", {"input_price": 1})], LATER)
    assert prices(db, oid)["INPUT"] == 10


def test_route_api_precedes_models_dev_and_litellm(db):
    run(db, [record(source, {"input_price": value}, provider="openrouter") for source, value in [
        ("litellm", 4), ("models.dev", 3), ("openrouter", 2),
    ]])
    assert prices(db, route(db, provider="OpenRouter")["id"])["INPUT"] == 2


def test_direct_and_openrouter_offerings_keep_separate_prices(db):
    canonical = "verification/shared-release"
    run(db, [
        record("official_provider", {"input_price": 3, "output_price": 9}, canonical=canonical),
        record("openrouter", {"input_price": 0, "output_price": 0},
               api_id="verification/model:free", provider="openrouter", canonical=canonical),
    ])
    direct = route(db)
    router = route(db, "verification/model:free", "OpenRouter")
    assert direct["model_id"] == router["model_id"]
    assert direct["id"] != router["id"]
    assert prices(db, direct["id"]) == {"INPUT": 3, "OUTPUT": 9}
    assert prices(db, router["id"]) == {"INPUT": 0, "OUTPUT": 0}
    assert (direct["free_status"], router["free_status"]) == ("PAID", "FREE")


def test_repeated_update_changes_neither_snapshot_nor_catalog_artifact(db, tmp_path):
    records = [record()]
    first = run(db, records)
    assert write_outputs(db, first, tmp_path / "data", NOW)["snapshot_changed"]
    before = encode(snapshot(db))
    path = tmp_path / "data" / "catalog.json"
    modified = path.stat().st_mtime_ns
    second = run(db, records, LATER)
    assert encode(snapshot(db)) == before
    assert not any(second[category] for category in second["records_changed"])
    assert not write_outputs(db, second, tmp_path / "data", LATER)["snapshot_changed"]
    assert path.stat().st_mtime_ns == modified


def test_conflicting_model_facts_from_same_source_do_not_churn_on_repeat(db):
    records = [
        record(fields={"open_weights": True}, api_id="variant-a", canonical="verification/shared"),
        record(fields={"open_weights": False}, api_id="variant-b", canonical="verification/shared"),
    ]
    run(db, records)
    before = encode(snapshot(db))
    run(db, records, LATER)
    assert encode(snapshot(db)) == before


def test_negative_price_is_quarantined_with_evidence_and_last_good_value(db):
    run(db, [record()])
    report = run(db, [record(fields={"input_price": -5})], LATER)
    oid = route(db)["id"]
    assert prices(db, oid)["INPUT"] == 2
    rejected = db.execute(
        "SELECT * FROM data_observations WHERE entity=? AND accepted=0", (f"offering:{oid}",),
    ).fetchone()
    assert json.loads(rejected["value_json"]) == -5
    assert rejected["source_url"] and rejected["evidence"]
    assert any(r["field"] == "input_price" for r in report["Manual-review items"])


def test_extreme_price_increase_requires_review(db):
    run(db, [record()])
    report = run(db, [record(fields={"input_price": 200})], LATER)
    assert prices(db, route(db)["id"])["INPUT"] == 2
    assert any("10x" in item["reason"] for item in report["Manual-review items"])


@pytest.mark.parametrize("suspicious", ["count", "priced", "zero"])
def test_source_collapse_or_mass_zero_is_quarantined_and_other_source_continues(db, suspicious):
    records = [record(api_id=f"model-{i}") for i in range(12)]
    run(db, records)
    original = {r["api_model_id"]: prices(db, route(db, r["api_model_id"])["id"]) for r in records}
    if suspicious == "count":
        proposed = records[:3]
    elif suspicious == "priced":
        proposed = [dict(r, fields={"context_window": 8192}) for r in records]
    else:
        proposed = [dict(r, fields={"input_price": 0, "output_price": 0}) for r in records]
    report = run(db, proposed + [record("official_provider", provider="other")], LATER)
    assert any(f["source"] == "models.dev" for f in report["Source failures"])
    assert route(db, provider="Other") is not None
    for api_id, expected in original.items():
        assert prices(db, route(db, api_id)["id"]) == expected
    assert db.execute("SELECT 1 FROM data_observations WHERE accepted=0 AND source='models.dev'").fetchone()


def test_total_quarantine_rolls_back_update(db):
    run(db, [record(api_id=f"model-{i}") for i in range(12)])
    before = encode(snapshot(db))
    with pytest.raises(ValueError, match="No source passed"):
        run(db, [record(api_id="model-0")], LATER)
    assert encode(snapshot(db)) == before


def test_discovery_is_not_release_and_announced_date_remains_separate(db):
    run(db, [record(fields={})])
    mid = route(db)["model_id"]
    model = db.execute("SELECT * FROM models WHERE id=?", (mid,)).fetchone()
    assert model["first_seen_at"] == NOW
    assert model["released_at"] is None
    run(db, [record("official_announcement", {"release_date": "2026-09-01"})], LATER)
    model = db.execute("SELECT * FROM models WHERE id=?", (mid,)).fetchone()
    assert model["first_seen_at"] == NOW
    assert model["released_at"] == "2026-09-01"
    assert model["release_date_kind"] == "official"


def test_month_precision_release_is_retained_without_inventing_a_day(db):
    run(db, [record(fields={"release_date": "2026-08"})])
    model = db.execute("SELECT * FROM models WHERE id=?", (route(db)["model_id"],)).fetchone()
    assert model["released_at"] == "2026-08"
    assert model["release_date_kind"] == "aggregator"


def test_benchmarks_require_publisher_evidence_and_never_accept_generic_scores(db):
    before = [tuple(r) for r in db.execute("SELECT * FROM benchmark_results ORDER BY id")]
    report = run(db, [record("models.dev", {"benchmark:swe-bench": 99.9})])
    assert priority("benchmark_publisher", "benchmark:swe-bench") < priority("official_provider", "benchmark:swe-bench")
    assert [tuple(r) for r in db.execute("SELECT * FROM benchmark_results ORDER BY id")] == before
    assert any(r["field"] == "benchmark:swe-bench" for r in report["Manual-review items"])
    assert db.execute("SELECT 1 FROM review_queue WHERE entity LIKE 'benchmark_result:%'").fetchone()


@pytest.mark.parametrize("corruption", ["negative_price", "foreign_key", "unknown_column", "free_without_prices"])
def test_invalid_snapshot_rolls_back_every_table_and_digest(db, tmp_path, corruption):
    run(db, [record()])
    before = encode(snapshot(db))
    document = snapshot(db)
    if corruption == "negative_price":
        document["tables"]["pricing_records"][0]["amount"] = -1
    elif corruption == "foreign_key":
        document["tables"]["pricing_records"][0]["offering_id"] = 999999999
    elif corruption == "unknown_column":
        document["tables"]["providers"][0]["injected_column"] = "bad"
    else:
        oid = route(db)["id"]
        for row in document["tables"]["provider_offerings"]:
            if row["id"] == oid:
                row["free_status"] = "FREE"
    path = tmp_path / "invalid.json"
    path.write_text(encode(document))
    with pytest.raises(ValueError):
        apply_snapshot(db, path)
    assert encode(snapshot(db)) == before
    assert db.execute("SELECT COUNT(*) FROM applied_snapshots").fetchone()[0] == 0


def test_valid_snapshot_applies_once_and_does_not_revert_local_changes(db, tmp_path):
    run(db, [record()])
    document = snapshot(db)
    expected = "Publisher-reviewed provider"
    document["tables"]["providers"][0]["name"] = expected
    path = tmp_path / "catalog.json"
    path.write_text(encode(document))
    apply_snapshot(db, path)
    ident = document["tables"]["providers"][0]["id"]
    assert db.execute("SELECT name FROM providers WHERE id=?", (ident,)).fetchone()[0] == expected
    with db:
        db.execute("UPDATE providers SET name='Local edit' WHERE id=?", (ident,))
    apply_snapshot(db, path)
    assert db.execute("SELECT name FROM providers WHERE id=?", (ident,)).fetchone()[0] == "Local edit"
    assert db.execute("SELECT COUNT(*) FROM applied_snapshots").fetchone()[0] == 1


def test_unchanged_mostly_free_provider_is_not_a_mass_zero_event(db):
    records = [record(api_id=f'model-{i}', fields={'input_price': 0 if i < 97 else 2, 'output_price': 0 if i < 97 else 6}) for i in range(101)]
    run(db, records)
    report = run(db, records, LATER)
    assert not report['Source failures']


def test_entire_provider_disappearance_is_flagged(db):
    records = [record(api_id=f'model-{i}', provider='vanishing') for i in range(12)]
    records += [record(api_id=f'model-{i}', provider='staying') for i in range(100)]
    run(db, records)
    report = run(db, [r for r in records if r['provider_key'] == 'staying'] + [record('official_provider', provider='other')], LATER)
    assert any('entire provider disappeared' in failure['error'] for failure in report['Source failures'])


def test_dry_run_never_changes_database_or_artifacts(db, tmp_path, monkeypatch):
    import hashlib
    import sys

    from app.data_update import main

    run(db, [record()])
    database = db.execute('PRAGMA database_list').fetchone()[2]
    before = hashlib.sha256(open(database, 'rb').read()).hexdigest()
    monkeypatch.setattr('app.update_sources.fetch_sources', lambda: ([record(fields={'input_price': 3})], [], {}))
    monkeypatch.setattr('app.update_sources.fetch_harness_changes', lambda: ([], [], {}))
    output = tmp_path / 'dry-output'
    monkeypatch.setattr(sys, 'argv', ['data_update', 'update', '--database', database, '--output-dir', str(output), '--dry-run'])
    main()
    assert hashlib.sha256(open(database, 'rb').read()).hexdigest() == before
    assert not output.exists()


def test_invalid_preexisting_import_data_is_preserved_as_quarantined_evidence(db):
    with db:
        oid = db.execute('SELECT id FROM provider_offerings LIMIT 1').fetchone()[0]
        db.execute("INSERT INTO pricing_records(offering_id,price_type,amount) VALUES(?,'INPUT',-1000000)", (oid,))
        db.execute('UPDATE provider_offerings SET context_limit=0 WHERE id=?', (oid,))
    report = run(db, [record()])
    assert not db.execute('SELECT 1 FROM pricing_records WHERE amount<0').fetchone()
    assert db.execute('SELECT context_limit FROM provider_offerings WHERE id=?', (oid,)).fetchone()[0] is None
    assert db.execute('SELECT 1 FROM data_observations WHERE value_json=? AND accepted=0', ('-1000000',)).fetchone()
    assert any('Legacy invalid price' in item['reason'] for item in report['Manual-review items'])

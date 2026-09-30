"""Offline checks for catalog precedence, quarantine, and atomic deployment."""

import json

import pytest

from app import create_app
from app.data_snapshot import apply_snapshot, encode, snapshot
from app.data_update import archive_historical_observations, priority, update, write_outputs
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


def test_historical_observations_are_archived_with_provenance_and_compacted(db, tmp_path):
    with db:
        old_id = db.execute("""INSERT INTO data_observations(entity,field,source,source_url,source_id,value_json,priority,observed_at,accepted,evidence)
          VALUES('offering:999','input_price','official_provider','https://example.test/pricing',NULL,'2',10,'2020-01-01T00:00:00+00:00',1,'published rate')""").lastrowid
        current_id = db.execute("""INSERT INTO data_observations(entity,field,source,source_url,source_id,value_json,priority,observed_at,accepted,evidence)
          VALUES('offering:999','output_price','official_provider','https://example.test/pricing',NULL,'3',10,'2026-09-19T00:00:00+00:00',1,'published rate')""").lastrowid
        selected_id = db.execute("""INSERT INTO data_observations(entity,field,source,source_url,source_id,value_json,priority,observed_at,accepted,evidence)
          VALUES('model:999','open_weights','official_provider','https://example.test/model',NULL,'true',10,'2020-01-01T00:00:00+00:00',1,'selected fact')""").lastrowid
        db.execute('INSERT INTO selected_facts(entity,field,observation_id) VALUES(?,?,?)', ('model:999','open_weights',selected_id))
        db.execute("""INSERT INTO review_queue(id,entity,proposed_change,sources,evidence,confidence,reason,status,created_at,resolved_at,resolution_note,triage_class)
          VALUES('resolved-test','plan:1','price', '[]','verified evidence','HIGH','reviewed','RESOLVED',?,?,'accepted','plan_change')""", (NOW,NOW))
        result = archive_historical_observations(db, tmp_path / 'history' / 'observations.sqlite3', NOW)
        db.commit()
    assert result['archived_observations'] == 1
    assert result['archived_resolved_reviews'] == 1
    assert db.execute('SELECT 1 FROM data_observations WHERE id=?', (old_id,)).fetchone() is None
    assert db.execute('SELECT 1 FROM data_observations WHERE id=?', (current_id,)).fetchone()
    assert db.execute('SELECT 1 FROM data_observations WHERE id=?', (selected_id,)).fetchone()
    assert db.execute("SELECT 1 FROM review_queue WHERE id='resolved-test'").fetchone() is None
    import sqlite3
    with sqlite3.connect(tmp_path / 'history' / 'observations.sqlite3') as archive:
        row = archive.execute('SELECT entity,field,source_url,evidence FROM archived_observations WHERE source_observation_id=?', (old_id,)).fetchone()
    assert row == ('offering:999', 'input_price', 'https://example.test/pricing', 'published rate')
    with sqlite3.connect(tmp_path / 'history' / 'observations.sqlite3') as archive:
        review = archive.execute("SELECT row_json FROM archived_reviews WHERE id='resolved-test'").fetchone()[0]
    assert json.loads(review)['resolution_note'] == 'accepted'


def test_documentation_source_revision_is_review_only(db, monkeypatch):
    from app import documentation_monitor
    assert documentation_monitor._json_shape({'plans': [{'price': 2}], 'active': True}) == {
        'active': 'bool', 'plans': [{'price': 'int'}]}
    sources = documentation_monitor.monitored_sources(db)
    if not sources:
        pytest.skip('migration fixture has no linked official documentation source')
    state = {'hash': 'a' * 64}
    def fake_fetch(source):
        return source, state['hash'], 'b' * 64, 200, None
    monkeypatch.setattr(documentation_monitor, '_fetch', fake_fetch)
    with db:
        first = documentation_monitor.monitor_documentation(db, NOW)
        state['hash'] = 'c' * 64
        second = documentation_monitor.monitor_documentation(db, LATER)
        saved_hash = db.execute('SELECT content_hash FROM documentation_monitor_state LIMIT 1').fetchone()[0]
        monkeypatch.setattr(documentation_monitor, '_fetch', lambda source: (source, None, None, None, 'Timeout'))
        failed = documentation_monitor.monitor_documentation(db, '2026-09-22T12:00:00+00:00')
        after_failure = db.execute('SELECT content_hash,status FROM documentation_monitor_state LIMIT 1').fetchone()
    assert first['failures'] == 0
    assert second['changed'] >= 1
    assert failed['failures'] >= 1
    assert after_failure['content_hash'] == saved_hash
    assert after_failure['status'] == 'ERROR'
    assert db.execute("SELECT COUNT(*) FROM review_queue WHERE status='PENDING' AND reason LIKE 'Official source changed%'").fetchone()[0] >= 1


def test_plan_updates_preserve_superseded_published_values(db):
    with db:
        plan = db.execute('SELECT * FROM plans LIMIT 1').fetchone()
        assert plan is not None
        db.execute('UPDATE plans SET monthly_price=COALESCE(monthly_price,0)+1 WHERE id=?', (plan['id'],))
    history = db.execute('SELECT * FROM plan_value_history WHERE plan_id=?', (plan['id'],)).fetchone()
    assert history is not None
    assert history['name'] == plan['name']
    assert history['source_id'] == plan['source_id']
    assert history['verified_at'] == plan['verified_at']


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


def test_provider_namespace_is_unresolved_until_exact_mapping(db):
    item = record("models.dev", {"input_price": 1, "output_price": 2},
                  api_id="deepseek-ai/DeepSeek-V4-Pro", provider="deepinfra")
    report = run(db, [item])
    route_row = route(db, item["api_model_id"], "DeepInfra")
    model = db.execute("SELECT identity_kind FROM models WHERE id=?", (route_row["model_id"],)).fetchone()
    assert model[0] == "UNKNOWN"
    assert report["Manual-review items"]
    assert prices(db, route_row["id"]) == {"INPUT": 1, "OUTPUT": 2}


def test_exact_identity_mapping_reconciles_route_and_keeps_offering_history(db):
    direct = record("official_provider", {"input_price": 3, "output_price": 9},
                    api_id="deepseek-v4-pro", provider="deepseek", canonical="deepseek/deepseek-v4-pro")
    routed = record("models.dev", {"input_price": 1, "output_price": 2},
                    api_id="deepseek-ai/DeepSeek-V4-Pro", provider="deepinfra")
    run(db, [direct, routed])
    model_id = route(db, direct["api_model_id"], "DeepSeek")["model_id"]
    provider_id = db.execute("SELECT id FROM providers WHERE name='DeepInfra'").fetchone()[0]
    source_id = db.execute("SELECT id FROM sources WHERE url=?", (routed["source_url"],)).fetchone()[0]
    db.execute("""INSERT INTO model_identity_mappings(provider_id,provider_model_id,model_id,
      evidence_source_id,evidence_url,evidence,confidence) VALUES(?,?,?,?,?,?,?)""",
      (provider_id, routed["api_model_id"], model_id, source_id, routed["source_url"],
       "Exact reviewed mapping in regression fixture", "HIGH"))
    run(db, [routed], LATER)
    routed_row = route(db, routed["api_model_id"], "DeepInfra")
    assert routed_row["model_id"] == model_id
    assert prices(db, routed_row["id"]) == {"INPUT": 1, "OUTPUT": 2}


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
    called = []
    monkeypatch.setattr('app.openrouter_routes.fetch_openrouter_variants', lambda: ([], [], {}))
    monkeypatch.setattr('app.openrouter_routes.sync_openrouter_variants', lambda *args: called.append('sync') or {'imported': 0, 'failures': 0})
    monkeypatch.setattr('app.documentation_monitor.monitor_documentation', lambda *args: {'checked': 0, 'changed': 0, 'failures': 0})
    output = tmp_path / 'dry-output'
    monkeypatch.setattr(sys, 'argv', ['data_update', 'update', '--database', database, '--output-dir', str(output), '--dry-run'])
    main()
    assert hashlib.sha256(open(database, 'rb').read()).hexdigest() == before
    assert not output.exists()
    assert called == ['sync']


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


def test_exported_shards_apply_and_reject_tampering(db, tmp_path):
    report = run(db, [record()])
    output = tmp_path / 'data'
    write_outputs(db, report, output, NOW)
    expected = encode(snapshot(db))
    apply_snapshot(db, output / 'catalog.json')
    assert encode(snapshot(db)) == expected
    manifest = json.loads((output / 'catalog.json').read_text())
    assert manifest['version'] == 2
    shard = output / manifest['tables']['models'][0]['path']
    shard.write_text('[]')
    # Force a different manifest digest so startup checks the supplied artifact.
    (output / 'catalog.json').write_text(json.dumps(manifest, indent=1))
    with pytest.raises(ValueError, match='checksum'):
        apply_snapshot(db, output / 'catalog.json')
    assert encode(snapshot(db)) == expected


def test_fresh_value_reappearing_after_legacy_baseline_wins_in_first_run(db):
    provider = db.execute("INSERT INTO providers(name) VALUES('Verification')").lastrowid
    mid = db.execute('SELECT id FROM models LIMIT 1').fetchone()[0]
    oid = db.execute("INSERT INTO provider_offerings(model_id,provider_id,api_model_id,source_id) VALUES(?,?,'verification-model',1)", (mid, provider)).lastrowid
    for price in (2, 3):
        db.execute("INSERT INTO pricing_records(offering_id,price_type,amount,source_id) VALUES(?,'INPUT',?,1)", (oid, price))
    db.commit()
    run(db, [record(fields={'input_price': 2})])
    assert prices(db, oid)['INPUT'] == 2
    before = encode(snapshot(db))
    run(db, [record(fields={'input_price': 2.0})], LATER)
    assert encode(snapshot(db)) == before


def test_equal_numeric_values_are_not_conflicts(db):
    report = run(db, [record('models.dev', {'input_price': 2}), record('litellm', {'input_price': 2.0})])
    oid = route(db)['id']
    assert not [r for r in report['Conflicts'] if r['entity'] == f'offering:{oid}']


def test_small_listing_removals_queue_expiry_review_without_erasing_prices(db):
    run(db, [record(api_id=f'model-{i}') for i in range(12)])
    report = run(db, [record(api_id=f'model-{i}') for i in range(11)], LATER)
    assert prices(db, route(db, 'model-11')['id'])['INPUT'] == 2
    assert any(r['field'] == 'listing removed' for r in report['Manual-review items'])


def test_snapshot_replacement_avoids_quadratic_foreign_key_scans(db, tmp_path):
    # Production has 100k observations. Deleting parents before their selections
    # made a second deployment exceed health-check timeouts despite valid data.
    with db:
        for ident in range(1, 1501):
            db.execute("INSERT INTO data_observations(id,entity,field,source,source_url,value_json,priority,observed_at,evidence) VALUES(?,?,'test','test','https://example.test','1',60,?,'fixture')", (ident, f'fixture:{ident}', NOW))
            db.execute("INSERT INTO selected_facts VALUES(?,'test',?)", (f'fixture:{ident}', ident))
    path = tmp_path / 'snapshot.json'
    path.write_text(encode(snapshot(db)))
    calls = 0

    def budget():
        nonlocal calls
        calls += 1
        return int(calls > 200)

    db.set_progress_handler(budget, 10000)
    try:
        apply_snapshot(db, path)
    finally:
        db.set_progress_handler(None, 0)
    assert db.execute('SELECT count(*) FROM selected_facts').fetchone()[0] == 1500


def test_published_snapshot_is_reconciled_before_new_fetch(db, tmp_path, monkeypatch):
    import sys

    from app.data_update import main

    report = run(db, [record()])
    base = tmp_path / 'published'
    write_outputs(db, report, base, NOW)
    oid = route(db)['id']
    with db:
        db.execute("UPDATE pricing_records SET amount=99 WHERE offering_id=? AND price_type='INPUT'", (oid,))
    database = db.execute('PRAGMA database_list').fetchone()[2]
    monkeypatch.setattr('app.update_sources.fetch_sources', lambda: ([record(fields={})], [], {}))
    monkeypatch.setattr('app.update_sources.fetch_harness_changes', lambda: ([], [], {}))
    monkeypatch.setattr('app.benchmark_sources.sync_publisher_results',
                        lambda *_: {"inserted": 0, "unmatched_models": {}, "failures": []})
    monkeypatch.setattr(sys, 'argv', ['data_update', 'update', '--database', database, '--base-snapshot', str(base / 'catalog.json'), '--output-dir', str(tmp_path / 'updated')])
    main()
    assert prices(db, oid)['INPUT'] == 2


def test_validation_rejects_duplicate_current_price(db):
    from app.data_update import validate

    run(db, [record()])
    oid = route(db)["id"]
    db.execute("INSERT INTO pricing_records(offering_id,price_type,amount,unit) VALUES(?,'INPUT',9,'per_1m_tokens')", (oid,))
    with pytest.raises(ValueError, match="Duplicate current price"):
        validate(db)


def test_validation_requires_active_offer_verification(db):
    from app.data_update import validate

    provider = db.execute("SELECT id FROM providers LIMIT 1").fetchone()[0]
    db.execute("INSERT INTO offers(provider_id,title,offer_type,status) VALUES(?,'Unverified','PROMO','ACTIVE')", (provider,))
    with pytest.raises(ValueError, match="verification timestamp"):
        validate(db)


def test_time_bound_provider_promotion_expires_and_keeps_source(db):
    provider = db.execute("SELECT id FROM providers WHERE name='OpenAI'").fetchone()[0]
    source = db.execute("SELECT id FROM sources WHERE name='OpenAI API pricing'").fetchone()[0]
    db.execute("""INSERT INTO offers(provider_id,title,offer_type,terms_url,starts_at,ends_at,
      source_id,status,last_verified_at,discount_percent,description)
      VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (provider, 'Verified provider promotion', 'PROMOTIONAL_DISCOUNT',
      'https://platform.openai.com/pricing', '2026-09-01', '2026-09-19', source,
      'ACTIVE', '2026-09-19', 10, 'Route-independent provider promotion.'))
    report = run(db, [record()], now=NOW)
    row = db.execute("SELECT * FROM offers WHERE title='Verified provider promotion'").fetchone()
    assert row['status'] == 'EXPIRED'
    assert row['source_id'] == source
    assert any(item['title'] == 'Verified provider promotion' for item in report['Expired offers'])

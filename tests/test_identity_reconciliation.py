"""Regression coverage for exact canonical identity reconciliation boundaries."""

import json

import pytest

from app import create_app
from app.db import get_db
from app.update_sources import _canonical, parse_openrouter
from scripts.reconcile_model_identities import run


@pytest.fixture
def db(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "identity.sqlite3"),
                      "APPLY_DATA_SNAPSHOT": False})
    with app.app_context():
        yield get_db()


def model(db, name, slug, kind="RELEASE"):
    return db.execute(
        """INSERT INTO models(canonical_name,vendor,modality,open_weights,canonical_slug,identity_kind)
           VALUES(?,'Unknown','text',0,?,?)""",
        (name, slug, kind),
    ).lastrowid


def provider(db, name):
    existing = db.execute("SELECT id FROM providers WHERE name=?", (name,)).fetchone()
    if existing:
        return existing[0]
    db.execute("INSERT INTO providers(name) VALUES(?)", (name,))
    return db.execute("SELECT id FROM providers WHERE name=?", (name,)).fetchone()[0]


def route(db, model_id, provider_id, api_model_id, source_id=None):
    return db.execute(
        """INSERT INTO provider_offerings(model_id,provider_id,api_model_id,source_id)
           VALUES(?,?,?,?)""",
        (model_id, provider_id, api_model_id, source_id),
    ).lastrowid


def test_openrouter_canonical_identity_disambiguates_exact_upstream_id(db, tmp_path):
    with db:
        source = db.execute("SELECT id FROM sources WHERE url='https://openrouter.ai/api/v1/models'").fetchone()[0]
        deepinfra = provider(db, "DeepInfra")
        openrouter = provider(db, "OpenRouter")
        nebius = provider(db, "Nebius")
        canonical = model(db, "Qwen3 32B", "alibaba/qwen3-32b")
        competing = model(db, "QWEN3 32B", "nebius/Qwen/Qwen3-32B")
        unresolved = model(db, "Qwen3 32b", "deepinfra/Qwen/Qwen3-32B", "UNKNOWN")
        route(db, canonical, openrouter, "qwen/qwen3-32b", source)
        route(db, competing, nebius, "Qwen/Qwen3-32B")
        offering = route(db, unresolved, deepinfra, "Qwen/Qwen3-32B")
        db.execute("INSERT INTO model_aliases(model_id,alias,provider_id,source_id) VALUES(?,?,?,?)",
                   (unresolved, "Qwen/Qwen3-32B", deepinfra, source))
        db.execute(
            """INSERT INTO model_identity_review(provider_id,provider_model_id,candidate_model_id,reason)
               VALUES(?,?,NULL,'candidate needs review')""",
            (deepinfra, "Qwen/Qwen3-32B"),
        )
        audit = tmp_path / "audit.json"
        report = run(db, audit)

    assert report["mappings_accepted_this_run"] == 1
    assert db.execute("SELECT model_id FROM provider_offerings WHERE id=?", (offering,)).fetchone()[0] == canonical
    assert db.execute("SELECT model_id FROM model_aliases WHERE provider_id=?", (deepinfra,)).fetchone()[0] == canonical
    mapping = db.execute(
        "SELECT status,evidence_url,evidence,confidence,verified_at FROM model_identity_mappings"
    ).fetchone()
    assert mapping[0] == "ACCEPTED"
    assert mapping[1] == "https://openrouter.ai/api/v1/models"
    assert "Exact provider model ID" in mapping[2]
    assert mapping[3] == "MEDIUM"
    assert mapping[4]
    assert db.execute("SELECT status FROM model_identity_review").fetchone()[0] == "RESOLVED"
    assert report["after"]["provider_routes"] == report["before"]["provider_routes"]
    assert json.loads(audit.read_text())["ambiguous_cases_intentionally_left_unresolved"] == 0


def test_exact_openrouter_duplicate_merge_preserves_routes_prices_and_redirects(db, tmp_path):
    with db:
        source = db.execute("SELECT id FROM sources WHERE url='https://openrouter.ai/api/v1/models'").fetchone()[0]
        openrouter = provider(db, "OpenRouter")
        deepinfra = provider(db, "DeepInfra")
        target = model(db, "Orion Qwen", "qwen/orion-qwen")
        duplicate = model(db, "ORION QWEN", "deepinfra/qwen/orion-qwen")
        route(db, target, openrouter, "qwen/orion-qwen", source)
        old_offering = route(db, duplicate, deepinfra, "qwen/orion-qwen")
        db.execute(
            """INSERT INTO pricing_records(offering_id,price_type,amount,source_id)
               VALUES(?,'INPUT',1.25,?)""",
            (old_offering, source),
        )
        db.execute(
            "INSERT INTO model_aliases(model_id,alias,provider_id,source_id) VALUES(?,?,?,?)",
            (duplicate, "qwen/orion-qwen", deepinfra, source),
        )
        report = run(db, tmp_path / "merge-audit.json")

    assert report["models_merged_this_run"] == 1
    assert db.execute("SELECT COUNT(*) FROM models WHERE id=?", (duplicate,)).fetchone()[0] == 0
    assert db.execute("SELECT model_id FROM provider_offerings WHERE id=?", (old_offering,)).fetchone()[0] == target
    assert db.execute("SELECT COUNT(*) FROM pricing_records WHERE offering_id=?", (old_offering,)).fetchone()[0] == 1
    assert db.execute("SELECT model_id FROM model_aliases WHERE provider_id=?", (deepinfra,)).fetchone()[0] == target
    redirect_row = db.execute(
        "SELECT old_slug,target_model_id,evidence_url FROM model_identity_redirects WHERE old_model_id=?",
        (duplicate,),
    ).fetchone()
    assert tuple(redirect_row) == ("deepinfra/qwen/orion-qwen", target, "https://openrouter.ai/api/v1/models")


def test_source_backed_exact_alias_merges_to_openrouter_canonical_model(db, tmp_path):
    with db:
        alias_source = db.execute("SELECT id FROM sources WHERE url='https://models.dev/api.json'").fetchone()[0]
        router_source = db.execute("SELECT id FROM sources WHERE url='https://openrouter.ai/api/v1/models'").fetchone()[0]
        deepinfra = provider(db, "DeepInfra")
        openrouter = provider(db, "OpenRouter")
        target = model(db, "Astra 14B", "lab/astra-14b")
        duplicate = model(db, "ASTRA 14B", "provider/astra-14b")
        route(db, target, openrouter, "lab/astra-14b", router_source)
        old_offering = route(db, duplicate, deepinfra, "provider/astra-14b")
        db.execute(
            "INSERT INTO model_aliases(model_id,alias,provider_id,source_id) VALUES(?,?,?,?)",
            (target, "provider/astra-14b", deepinfra, alias_source),
        )
        report = run(db, tmp_path / "alias-audit.json")

    assert report["models_merged_this_run"] == 1
    assert db.execute("SELECT model_id FROM provider_offerings WHERE id=?", (old_offering,)).fetchone()[0] == target
    redirect_row = db.execute(
        "SELECT evidence_source_id,evidence_url,evidence FROM model_identity_redirects WHERE old_model_id=?",
        (duplicate,),
    ).fetchone()
    assert redirect_row[0] == alias_source
    assert redirect_row[1] == "https://models.dev/api.json"
    assert "Source-backed alias" in redirect_row[2]


def test_similar_names_dated_releases_and_scoped_ids_stay_separate(db, tmp_path):
    with db:
        provider_id = provider(db, "Example Provider")
        similar = model(db, "Orion 8B Mini", "example/orion-8b-mini")
        unresolved = model(db, "Orion 8B", "example-provider/orion-8b", "UNKNOWN")
        route(db, similar, provider_id, "orion-8b-mini")
        route(db, unresolved, provider_id, "orion-8b")
        pending_version = model(db, "ORION 8B Release", "example-provider/orion-8b-2026-08-01", "UNKNOWN")
        version_provider = provider(db, "Versioned Gateway")
        version_target = model(db, "orion 8b release", "example/orion-8b-2026-07-01")
        route(db, version_target, version_provider, "orion-8b-2026-07-01")
        route(db, pending_version, version_provider, "orion-8b-2026-08-01")
        db.execute("INSERT INTO model_identity_review(provider_id,provider_model_id,reason) VALUES(?,?,?)",
                   (provider_id, "orion-8b", "similar name only"))
        db.execute("INSERT INTO model_identity_review(provider_id,provider_model_id,reason) VALUES(?,?,?)",
                   (version_provider, "orion-8b-2026-08-01", "dated release needs proof"))
        report = run(db, tmp_path / "audit.json")

    assert report["mappings_accepted_this_run"] == 0
    assert report["after"]["unresolved_provider_identities"] == 2
    statuses = {row[0]: row[1] for row in db.execute(
        "SELECT provider_model_id,status FROM model_identity_mappings"
    )}
    assert statuses == {"orion-8b-2026-08-01": "PENDING"}
    assert db.execute("SELECT model_id FROM provider_offerings WHERE api_model_id='orion-8b'").fetchone()[0] == unresolved


def test_versioned_and_provider_scoped_identifiers_are_not_normalized_away():
    assert _canonical("openai", "gpt-5.4-2026-08-01") != _canonical("openai", "gpt-5.4-2026-09-01")
    assert _canonical("openai", "model-x") != _canonical("azure", "model-x")
    assert _canonical("openai", "gpt-latest") != _canonical("openai", "gpt-5.4")


def test_merged_model_slug_and_numeric_id_redirect(tmp_path):
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "redirects.sqlite3"),
        "APPLY_DATA_SNAPSHOT": False,
    })
    with app.app_context():
        db = get_db()
        with db:
            target = model(db, "Redirect Target", "vendor/redirect-target")
            db.execute(
                """INSERT INTO model_identity_redirects(old_model_id,old_slug,old_name,target_model_id,
                     evidence_url,evidence,verified_at) VALUES(?,?,?,?,?,?,?)""",
                (99999, "legacy/vendor-model", "Legacy Vendor Model", target,
                 "https://openrouter.ai/api/v1/models", "Exact canonical route ID", "2026-09-30"),
            )
    client = app.test_client()
    numeric = client.get("/models/99999", follow_redirects=False)
    slug = client.get("/models/legacy/vendor-model", follow_redirects=False)
    api = client.get("/api/v1/models/legacy/vendor-model", follow_redirects=False)
    assert numeric.status_code == slug.status_code == api.status_code == 301
    assert numeric.headers["Location"].endswith("/models/vendor/redirect-target")
    assert slug.headers["Location"].endswith("/models/vendor/redirect-target")
    assert api.headers["Location"].endswith("/api/v1/models/vendor/redirect-target")


def test_openrouter_free_and_batch_modifiers_keep_the_same_model_identity():
    records = parse_openrouter(
        {"data": [{"id": "openai/gpt-test:free"}, {"id": "openai/gpt-test:batch"}]}
    )
    assert {row["api_model_id"] for row in records} == {"openai/gpt-test:free", "openai/gpt-test:batch"}
    assert {row["canonical_slug"] for row in records} == {"openai/gpt-test"}


def test_models_dev_canonical_model_id_is_explicit_evidence():
    from app.update_sources import parse_models_dev

    records = parse_models_dev({"deepinfra": {"name": "DeepInfra", "models": {
        "vendor/private-alias": {"name": "Orion 8B", "canonical_model_id": "orion/orion-8b-2026-08-01"}
    }}})
    assert records[0]["canonical_model_id"] == "orion/orion-8b-2026-08-01"
    assert records[0]["canonical_slug"] == "orion/orion-8b-2026-08-01"


def test_published_well_known_model_families_have_shared_provider_routes(tmp_path):
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "published-catalog.sqlite3"),
        "APPLY_DATA_SNAPSHOT": True,
    })
    families = {
        "openai/gpt-oss-120b": True,
        "openai/gpt-5.4": True,
        "anthropic/claude-sonnet-4-6": True,
        "google/gemma-4-31b-it": True,
        "deepseek/deepseek-v4-flash": True,
        "zhipuai/glm-5.3": True,
        "alibaba/qwen3.8-27b": True,
        "mistral/mistral-large-3": False,
        "moonshotai/kimi-k3": True,
        "minimax/MiniMax-M3": True,
    }
    with app.app_context():
        db = get_db()
        for slug, has_openrouter in families.items():
            row = db.execute(
                """SELECT COUNT(DISTINCT p.id) providers,
                          SUM(CASE WHEN p.name='OpenRouter' THEN 1 ELSE 0 END) openrouter_routes
                   FROM models m JOIN provider_offerings o ON o.model_id=m.id
                   JOIN providers p ON p.id=o.provider_id WHERE m.canonical_slug=?""",
                (slug,),
            ).fetchone()
            assert row["providers"] >= 2, slug
            assert bool(row["openrouter_routes"]) is has_openrouter, slug
        unresolved_slug = db.execute(
            """SELECT m.canonical_slug FROM models m JOIN provider_offerings o ON o.model_id=m.id
               WHERE m.identity_kind='UNKNOWN' ORDER BY m.canonical_slug LIMIT 1"""
        ).fetchone()[0]
    response = app.test_client().get(f"/api/v1/models/{unresolved_slug}")
    assert response.status_code == 200
    assert response.json["data"]["identity_status"] == "UNRESOLVED"

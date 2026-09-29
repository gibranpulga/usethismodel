import json

from app import create_app
from app.db import get_db
from app.openrouter_routes import (
    fetch_openrouter_variants,
    parse_endpoint_payload,
    sync_openrouter_variants,
)


def payload(discount=0.5, prompt="0.000001", completion="0.000002", status=0, params=None):
    return {"data": {"id": "z-ai/glm-5.3", "name": "GLM 5.3", "architecture": {
        "input_modalities": ["text", "image"], "output_modalities": ["text"]}, "endpoints": [{
        "name": "Example | glm", "provider_name": "Example", "tag": "example/fp8", "status": status,
        "quantization": "fp8", "context_length": 1000000, "max_completion_tokens": 1000,
        "supported_parameters": params if params is not None else ["tools", "structured_outputs"],
        "supports_tool_choice": {"auto": True},
        "pricing": {"prompt": prompt, "completion": completion, "discount": discount},
    }]}}


def test_endpoint_parser_keeps_route_scope_and_infers_original_price():
    row = parse_endpoint_payload(payload(), "https://example.test/endpoints")[0]
    assert row["provider_tag"] == "example/fp8"
    assert row["input_price"] == 1
    assert row["original_input_price"] == 2
    assert row["discount_percent"] == 50
    assert row["tool_support"] == "YES"
    assert row["structured_output_support"] == "YES"
    assert json.loads(row["input_modalities_json"]) == ["text", "image"]


def test_only_explicit_double_zero_is_free():
    assert parse_endpoint_payload(payload(0, "0", "0"), "x")[0]["is_free"] == 1
    assert parse_endpoint_payload(payload(0, None, None), "x")[0]["is_free"] == 0
    assert parse_endpoint_payload(payload(0, "0", "0.1"), "x")[0]["is_free"] == 0


def test_negative_discount_is_a_markup_not_an_offer():
    row = parse_endpoint_payload(payload(-0.2), "x")[0]
    assert row["discount_percent"] == -20
    assert row["original_price_inferred"] == 0


def test_fetch_isolates_per_model_failure():
    catalog = {"data": [{"id": "z-ai/glm-5.3"}, {"id": "bad/model"}]}
    def fetch(url):
        if "bad/model" in url:
            raise OSError("offline")
        return payload()
    rows, failures, manifest = fetch_openrouter_variants(fetch, catalog, workers=2)
    assert len(rows) == 1 and failures[0]["model_id"] == "bad/model"
    assert manifest["models_succeeded"] == 1


def test_sync_creates_route_specific_offer_and_preserves_first_seen(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "catalog.sqlite3")})
    with app.app_context():
        db = get_db()
        row = parse_endpoint_payload(payload(), "https://example.test/endpoints")[0]
        first = sync_openrouter_variants(db, [row], [], {"models_attempted": 1, "models_succeeded": 1, "schema_hash": "a"}, "2026-09-29T12:00:00+00:00")
        db.commit()
        assert first["imported"] == 1
        variant = db.execute("SELECT * FROM openrouter_route_variants WHERE provider_tag='example/fp8'").fetchone()
        offer = db.execute("SELECT * FROM offers WHERE route_variant_id=?", (variant["id"],)).fetchone()
        assert offer["status"] == "ACTIVE" and offer["discount_percent"] == 50
        assert offer["original_price_inferred"] == 1
        changed = parse_endpoint_payload(payload(0.25), "https://example.test/endpoints")[0]
        sync_openrouter_variants(db, [changed], [], {"models_attempted": 1, "models_succeeded": 1, "schema_hash": "a"}, "2026-09-30T12:00:00+00:00")
        db.commit()
        assert db.execute("SELECT count(*) FROM openrouter_route_variants WHERE provider_tag='example/fp8'").fetchone()[0] == 1
        assert db.execute("SELECT first_seen_at FROM openrouter_route_variants WHERE id=?", (variant["id"],)).fetchone()[0].startswith("2026-09-29")

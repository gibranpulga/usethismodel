"""Offline regression checks for public catalog semantics and failure isolation."""

import pytest

from app.update_sources import (
    LITELLM,
    MODELS_DEV,
    OPENROUTER,
    fetch_harness_changes,
    fetch_sources,
    parse_litellm,
    parse_models_dev,
    parse_openrouter,
)


def models_dev(item=None):
    return {"openai": {"name": "OpenAI", "models": {"gpt-test": item or {"name": "Test"}}}}


def openrouter(item=None):
    return {"data": [item or {"id": "openai/gpt-test"}]}


def litellm(item=None):
    return {"gpt-test": item or {"litellm_provider": "openai", "mode": "chat"}}


def test_models_dev_units_explicit_identity_and_false():
    record = parse_models_dev(
        models_dev(
            {
                "canonical_model_id": "openai/exact-release-2026-09-01",
                "cost": {"input": 0, "output": 3.75, "cache_read": 0.1},
                "limit": {"context": 128000, "output": 4096},
                "tool_call": False,
                "reasoning": True,
                "open_weights": False,
                "modalities": {"input": ["text", "image"]},
                "release_date": "2026-09",
                "last_updated": "2026-09-29",
            }
        )
    )[0]
    assert record["canonical_slug"] == "openai/exact-release-2026-09-01"
    assert record["source_kind"] == "aggregator"
    assert record["priority"] == 30
    assert record["fields"] == {
        "input_price": 0,
        "output_price": 3.75,
        "cache_read_price": 0.1,
        "context_window": 128000,
        "max_output_tokens": 4096,
        "tool_calling": False,
        "reasoning": True,
        "vision": True,
        "open_weights": False,
        "release_date": "2026-09",
    }


def test_no_invented_facts_or_unqualified_cross_provider_merge():
    payload = {
        provider: {"models": {"same-name:free": {"last_updated": "2026-09-29"}}}
        for provider in ("first", "second")
    }
    records = parse_models_dev(payload)
    assert [r["canonical_slug"] for r in records] == [
        "first/same-name:free",
        "second/same-name:free",
    ]
    assert all(r["fields"] == {} for r in records)


def test_openrouter_units_variants_and_created_not_release():
    record = parse_openrouter(
        openrouter(
            {
                "id": "openai/test:free",
                "canonical_slug": "openai/test-release",
                "created": 1790000000,
                "pricing": {
                    "prompt": "0",
                    "completion": "0.000003",
                    "input_cache_read": 0,
                    "input_cache_write": "0.0000005",
                },
                "supported_parameters": ["tools", "reasoning", "structured_outputs"],
                "architecture": {"input_modalities": ["text"]},
            }
        )
    )[0]
    assert record["api_model_id"] == "openai/test:free"
    assert record["canonical_slug"] == "openai/test-release"
    assert record["source_kind"] == "route_api"
    assert record["priority"] == 20
    assert record["fields"] == {
        "input_price": 0,
        "output_price": 3,
        "cache_read_price": 0,
        "cache_write_price": 0.5,
        "tool_calling": True,
        "reasoning": True,
        "structured_output": True,
        "vision": False,
    }


def test_openrouter_absent_parameters_are_unknown():
    record = parse_openrouter(
        openrouter({"id": "lab/model", "supported_parameters": ["response_format"]})
    )[0]
    assert record["fields"] == {}


def test_gateway_vendor_ids_share_canonical_identity_and_route_suffixes_do_not_split():
    gateway = parse_models_dev({"gateway": {"models": {"openai/gpt-next": {}}}})[0]
    router = parse_openrouter(openrouter({"id": "openai/gpt-next:batch"}))[0]
    lite = parse_litellm({"openrouter/openai/gpt-next:batch": {
        "litellm_provider": "openrouter", "mode": "chat"}})[0]
    assert gateway["canonical_slug"] == "openai/gpt-next"
    assert router["canonical_slug"] == "openai/gpt-next"
    assert lite["canonical_slug"] == "openai/gpt-next"


@pytest.mark.parametrize("modifier", [":free", ":floor", ":nitro", ":online", ":batch"])
def test_openrouter_behavior_modifiers_do_not_create_distinct_model_identity(modifier):
    row = parse_openrouter(openrouter({"id": "openai/gpt-next" + modifier}))[0]
    assert row["canonical_slug"] == "openai/gpt-next"


@pytest.mark.parametrize("value", ["NaN", "Infinity", True, "bad"])
def test_invalid_prices_reject_snapshot(value):
    with pytest.raises(ValueError):
        parse_openrouter(openrouter({"id": "test", "pricing": {"prompt": value}}))


def test_negative_prices_preserved_for_core_quarantine():
    record = parse_openrouter(openrouter({"id": "test", "pricing": {"prompt": -1}}))[0]
    assert record["fields"]["input_price"] == -1_000_000


def test_bad_limits_preserved_for_quarantine_and_unknown_booleans_omitted():
    record = parse_models_dev(
        models_dev(
            {
                "limit": {"context": 0, "output": 2.3},
                "release_date": "2026-02-30",
                "tool_call": "false",
                "open_weights": 0,
            }
        )
    )[0]
    assert record["fields"] == {"context_window": 0, "max_output_tokens": 2.3}


def test_litellm_transports_units_and_legacy_limit_not_conflated():
    record = parse_litellm(
        {
            "gemini/gemini-test": {
                "litellm_provider": "gemini",
                "mode": "chat",
                "input_cost_per_token": 0.0000001,
                "output_cost_per_token": 0,
                "cache_creation_input_token_cost": 0.000002,
                "max_tokens": 8000,
                "max_input_tokens": 32000,
                "max_output_tokens": 4000,
                "supports_function_calling": False,
                "supports_vision": True,
            }
        }
    )[0]
    assert record["provider_key"] == "google"
    assert record["api_model_id"] == "gemini-test"
    assert record["canonical_slug"] == "google/gemini-test"
    assert record["fields"] == {
        "input_price": 0.1,
        "output_price": 0,
        "cache_write_price": 2,
        "max_output_tokens": 4000,
        "tool_calling": False,
        "vision": True,
    }


def test_litellm_unsupported_routes_and_nonlanguage_models_skipped():
    assert (
        parse_litellm(
            {
                "sample_spec": {},
                "embedding": {"litellm_provider": "openai", "mode": "embedding"},
                "deployment": {"litellm_provider": "azure", "mode": "chat"},
                "unknown": {"litellm_provider": "unknown", "mode": "chat"},
            }
        )
        == []
    )


def test_failed_source_is_atomic_and_failure_text_sanitized():
    def fetch(url):
        if url == MODELS_DEV:
            return models_dev()
        if url == OPENROUTER:
            return {"data": [{"id": "valid"}, {"not_id": "invalid"}]}
        raise OSError("secret=do-not-log")

    records, failures, manifests = fetch_sources(fetch)
    assert len(records) == 1
    assert {f["source"] for f in failures} == {"openrouter", "litellm"}
    assert "secret" not in str(failures)
    assert list(manifests) == ["models.dev"]
    assert manifests["models.dev"]["count"] == 1
    assert len(manifests["models.dev"]["hash"]) == 64


def test_manifests_are_stable_and_empty_snapshot_fails():
    payloads = {MODELS_DEV: models_dev(), OPENROUTER: openrouter(), LITELLM: litellm()}
    first = fetch_sources(payloads.__getitem__)
    second = fetch_sources(payloads.__getitem__)
    assert first == second
    assert first[1] == []
    payloads[OPENROUTER] = {"data": []}
    records, failures, manifests = fetch_sources(payloads.__getitem__)
    assert len(records) == 2
    assert failures[0]["source"] == "openrouter"
    assert "openrouter" not in manifests


def test_litellm_duplicate_alias_conflicts_preserved_for_review():
    base = {"litellm_provider": "openai", "mode": "chat", "input_cost_per_token": 0.000001}
    records = parse_litellm(
        {
            "gpt-test": base,
            "openai/gpt-test": {**base, "input_cost_per_token": 0.000002, "supports_vision": True},
        }
    )
    assert len(records) == 1
    assert records[0]["fields"] == {"vision": True}
    assert records[0]["rejected_fields"] == {"input_price": [1, 2]}


def test_harness_monitor_returns_revision_only_and_stable_manifest():
    payload = [
        {
            "sha": "a" * 40,
            "commit": {
                "committer": {"date": "2026-09-29T12:00:00Z"},
                "message": "Update supported providers\nMore detail",
            },
        }
    ]
    records, failures, manifests = fetch_harness_changes(lambda url: payload)
    assert failures == []
    assert records[0]["content_hash"] == "a" * 40
    assert records[0]["source_kind"] == "official_docs"
    assert records[0]["evidence"]["title"] == "Update supported providers"
    assert "fields" not in records[0]
    assert manifests["hermes-official-docs"]["hash"] == "a" * 40


def test_harness_monitor_failure_is_not_an_empty_success():
    assert fetch_harness_changes(lambda url: [])[1] == [
        {
            "source": "hermes-official-docs",
            "error": "Fetch or validation failed (ValueError)",
        }
    ]

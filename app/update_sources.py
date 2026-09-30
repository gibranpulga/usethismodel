"""Read-only adapters for the proposed-update pipeline.

No adapter writes to the database. Missing facts are omitted, never synthesized as
zero/False. See docs/update-sources.md for identity and evidence boundaries.
"""

import hashlib
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen

MODELS_DEV = "https://models.dev/api.json"
OPENROUTER = "https://openrouter.ai/api/v1/models"
LITELLM = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)

# Explicit transport aliases only: never infer a provider from a display name.
LITELLM_PROVIDERS = {
    "openai": ("openai", "OpenAI"),
    "anthropic": ("anthropic", "Anthropic"),
    "gemini": ("google", "Google"),
    "openrouter": ("openrouter", "OpenRouter"),
    "deepseek": ("deepseek", "DeepSeek"),
    "mistral": ("mistral", "Mistral"),
    "xai": ("xai", "xAI"),
    "groq": ("groq", "Groq"),
    "cerebras": ("cerebras", "Cerebras"),
    "deepinfra": ("deepinfra", "Deep Infra"),
    "together_ai": ("togetherai", "Together AI"),
    "fireworks_ai": ("fireworks-ai", "Fireworks AI"),
    "perplexity": ("perplexity", "Perplexity"),
    "cohere_chat": ("cohere", "Cohere"),
    "cohere": ("cohere", "Cohere"),
    "sambanova": ("sambanova", "SambaNova"),
    "nebius": ("nebius", "Nebius"),
    "novita": ("novita-ai", "Novita AI"),
}


def _fetch(url):
    request = Request(
        url,
        headers={
            "User-Agent": "UseThisModel proposed-update monitor/1.0",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=45) as response:
        return json.load(response)


def _object(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"Invalid {label}: expected object")
    return value


def _identifier(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError(f"Invalid {label}: expected nonempty identifier")
    return value


def _number(value, multiplier=1):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean is not a numeric observation")
    try:
        number = Decimal(str(value)) * multiplier
        result = float(number)
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise ValueError("Invalid numeric observation") from exc
    if not math.isfinite(result):
        raise ValueError("Non-finite numeric observation")
    return result


def _limit(value):
    number = _number(value)
    return int(number) if number is not None and number.is_integer() else number


def _release_date(value):
    # Preserve month precision; never manufacture a day from a partial date.
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", value):
        return None
    try:
        date.fromisoformat(value + "-01" if len(value) == 7 else value)
        return value
    except ValueError:
        return None


def _known(fields):
    return {key: value for key, value in fields.items() if value is not None}


def _bool(value):
    return value if isinstance(value, bool) else None


def _vision(modalities):
    if isinstance(modalities, list) and modalities and all(isinstance(v, str) for v in modalities):
        return "image" in modalities
    return None


def _canonical(provider, api_id, explicit=None):
    if explicit:
        return _identifier(explicit, "canonical model ID")
    # A vendor-qualified model ID remains canonical across gateways. Only an
    # unqualified ID is provider-scoped. No case/date stripping or fuzzy merge.
    return api_id if "/" in api_id else f"{provider}/{api_id}"


def _record(source, url, kind, priority, provider, provider_name, api_id, canonical, name, fields, explicit_canonical=None):
    return {
        "source": source,
        "source_url": url,
        "source_kind": kind,
        "priority": priority,
        "provider_key": provider,
        "provider_name": provider_name,
        "api_model_id": api_id,
        "canonical_slug": canonical,
        "canonical_model_id": explicit_canonical,
        "name": name,
        "fields": _known(fields),
    }


def parse_models_dev(payload):
    records = []
    for provider_key, provider in _object(payload, "Models.dev catalog").items():
        _identifier(provider_key, "provider ID")
        provider = _object(provider, "Models.dev provider")
        models = _object(provider.get("models"), "Models.dev models")
        for api_id, item in models.items():
            _identifier(api_id, "model ID")
            item = _object(item, "Models.dev model")
            cost = _object(item.get("cost") or {}, "Models.dev cost")
            limits = _object(item.get("limit") or {}, "Models.dev limits")
            modalities = _object(item.get("modalities") or {}, "Models.dev modalities")
            fields = {
                "input_price": _number(cost.get("input")),
                "output_price": _number(cost.get("output")),
                "cache_read_price": _number(cost.get("cache_read")),
                "cache_write_price": _number(cost.get("cache_write")),
                "context_window": _limit(limits.get("context")),
                "max_output_tokens": _limit(limits.get("output")),
                "tool_calling": _bool(item.get("tool_call")),
                "vision": _vision(modalities.get("input")),
                "reasoning": _bool(item.get("reasoning")),
                "structured_output": _bool(item.get("structured_output")),
                "open_weights": _bool(item.get("open_weights")),
                "release_date": _release_date(item.get("release_date")),
            }
            canonical = _canonical(provider_key, api_id, item.get("canonical_model_id"))
            records.append(
                _record(
                    "models.dev",
                    MODELS_DEV,
                    "aggregator",
                    30,
                    provider_key,
                    provider.get("name") or provider_key,
                    api_id,
                    canonical,
                    item.get("name") or api_id,
                    fields,
                    item.get("canonical_model_id"),
                )
            )
    return records


def parse_openrouter(payload):
    data = _object(payload, "OpenRouter catalog").get("data")
    if not isinstance(data, list):
        raise ValueError("Invalid OpenRouter data: expected array")
    records = []
    for item in data:
        item = _object(item, "OpenRouter model")
        api_id = _identifier(item.get("id"), "OpenRouter model ID")
        pricing = _object(item.get("pricing") or {}, "OpenRouter pricing")
        top = _object(item.get("top_provider") or {}, "OpenRouter top provider")
        arch = _object(item.get("architecture") or {}, "OpenRouter architecture")
        params = item.get("supported_parameters")
        params = params if isinstance(params, list) else []
        fields = {
            "input_price": _number(pricing.get("prompt"), 1_000_000),
            "output_price": _number(pricing.get("completion"), 1_000_000),
            "cache_read_price": _number(pricing.get("input_cache_read"), 1_000_000),
            "cache_write_price": _number(pricing.get("input_cache_write"), 1_000_000),
            "context_window": _limit(item.get("context_length")),
            "max_output_tokens": _limit(top.get("max_completion_tokens")),
            # Parameter absence isn't an explicit denial of a capability.
            "tool_calling": True if "tools" in params else None,
            "reasoning": True if "reasoning" in params or "reasoning_effort" in params else None,
            "structured_output": True if "structured_outputs" in params else None,
            "vision": _vision(arch.get("input_modalities")),
        }
        records.append(
            _record(
                "openrouter",
                OPENROUTER,
                "route_api",
                20,
                "openrouter",
                "OpenRouter",
                api_id,
                (item.get("canonical_slug") or api_id).removesuffix(":batch").removesuffix(":free"),
                item.get("name") or api_id,
                fields,
            )
        )
    return records


def parse_litellm(payload):
    records = []
    for key, item in _object(payload, "LiteLLM catalog").items():
        if key == "sample_spec":
            continue
        item = _object(item, "LiteLLM model")
        transport = item.get("litellm_provider")
        if transport not in LITELLM_PROVIDERS or item.get("mode") not in ("chat", "completion"):
            continue
        provider, name = LITELLM_PROVIDERS[transport]
        _identifier(key, "LiteLLM model ID")
        api_id = key.removeprefix(transport + "/")
        fields = {
            "input_price": _number(item.get("input_cost_per_token"), 1_000_000),
            "output_price": _number(item.get("output_cost_per_token"), 1_000_000),
            "cache_read_price": _number(item.get("cache_read_input_token_cost"), 1_000_000),
            "cache_write_price": _number(item.get("cache_creation_input_token_cost"), 1_000_000),
            # max_tokens is legacy and may mean input OR output; never use it.
            "max_output_tokens": _limit(item.get("max_output_tokens")),
            "tool_calling": _bool(item.get("supports_function_calling")),
            "vision": _bool(item.get("supports_vision")),
            "reasoning": _bool(item.get("supports_reasoning")),
            "structured_output": _bool(item.get("supports_response_schema")),
        }
        records.append(
            _record(
                "litellm",
                LITELLM,
                "aggregator",
                40,
                provider,
                name,
                api_id,
                _canonical(provider, api_id).removesuffix(":batch").removesuffix(":free"),
                api_id,
                fields,
            )
        )
    merged = {}
    for record in records:
        identity = (record["provider_key"], record["api_model_id"])
        if identity not in merged:
            merged[identity] = record
            continue
        existing = merged[identity]
        rejected = existing.setdefault("rejected_fields", {})
        for field, value in record["fields"].items():
            if field in rejected:
                if value not in rejected[field]:
                    rejected[field].append(value)
            elif field in existing["fields"] and existing["fields"][field] != value:
                rejected[field] = [existing["fields"].pop(field), value]
            else:
                existing["fields"][field] = value
    return list(merged.values())


SOURCES = (
    ("models.dev", MODELS_DEV, parse_models_dev),
    ("openrouter", OPENROUTER, parse_openrouter),
    ("litellm", LITELLM, parse_litellm),
)


def fetch_sources(fetcher=None):
    """Return (records, failures, manifests), with atomic success per source.

    ``fetcher(url) -> decoded JSON`` is injectable for offline tests. Callers MUST
    retain prior observations for sources in failures. A success manifest hashes
    canonical JSON of the received payload, not the derived fields.
    """
    fetcher = fetcher or _fetch
    records, failures, manifests = [], [], {}
    with ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        futures = [pool.submit(fetcher, url) for _, url, _ in SOURCES]
        for (source, url, parser), future in zip(SOURCES, futures, strict=True):
            try:
                payload = future.result()
                source_records = parser(payload)
                if not source_records:
                    raise ValueError("Empty source snapshot")
                encoded = json.dumps(
                    payload, sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()
                digest = hashlib.sha256(encoded).hexdigest()
            except Exception as exc:
                # Do not leak remote response bodies, URL query strings, or
                # injected fetcher credentials into logs or proposal artifacts.
                failures.append(
                    {
                        "source": source,
                        "error": f"Fetch or validation failed ({type(exc).__name__})",
                    }
                )
                continue
            records.extend(source_records)
            schema = sorted({key for record in source_records for key in record.get("fields", {})})
            manifests[source] = {
                "count": len(source_records),
                "hash": digest,
                "schema_hash": hashlib.sha256(json.dumps(schema).encode()).hexdigest(),
                "url": url,
            }
    return records, failures, manifests


HERMES_DOCS_COMMITS = (
    "https://api.github.com/repos/NousResearch/hermes-agent/commits?path=website%2Fdocs&per_page=1"
)


def fetch_harness_changes(fetcher=None):
    """Fetch official documentation revision evidence; infer no capability facts.

    Return (records, failures, manifests), without persisting the baseline. The
    caller compares content_hash with its last known revision and queues review.
    """
    source = "hermes-official-docs"
    try:
        payload = (fetcher or _fetch)(HERMES_DOCS_COMMITS)
        if not isinstance(payload, list) or not payload:
            raise ValueError("Invalid Hermes documentation commit response")
        item = _object(payload[0], "Hermes documentation commit")
        sha = item.get("sha")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Invalid Hermes documentation revision")
        commit = _object(item.get("commit"), "Hermes commit metadata")
        committer = _object(commit.get("committer") or {}, "Hermes committer")
        record = {
            "entity": "harness",
            "name": "Hermes Agent",
            "source": source,
            "source_kind": "official_docs",
            "source_url": HERMES_DOCS_COMMITS,
            "url": f"https://github.com/NousResearch/hermes-agent/commit/{sha}",
            "content_hash": sha,
            "evidence": {
                "commit_sha": sha,
                "committed_at": committer.get("date"),
                "title": str(commit.get("message") or "").split("\n", 1)[0][:500],
                "docs_url": "https://hermes-agent.nousresearch.com/docs/",
                "path": "website/docs",
                "meaning": "Documentation revision changed; capabilities require review.",
            },
        }
        return [record], [], {source: {"count": 1, "hash": sha, "url": HERMES_DOCS_COMMITS}}
    except Exception as exc:
        return (
            [],
            [{"source": source, "error": f"Fetch or validation failed ({type(exc).__name__})"}],
            {},
        )

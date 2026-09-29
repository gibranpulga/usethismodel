# Structured update sources

`app/update_sources.py` fetches public metadata only. It does not update the catalog
or infer compatibility from model names. `fetch_sources(fetcher=None)` returns
`(records, failures, manifests)`; an injectable `fetcher(url)` returns decoded JSON
for deterministic offline checks. Each source is fetched once with a 45-second
timeout, concurrently with the others. No credentials are required or sent.

A record contains `source`, `source_url`, `source_kind`, `priority`, `provider_key`,
`provider_name`, `api_model_id`, `canonical_slug`, `name`, and `fields`. Lower
priority numbers are preferred. The current feeds are:

| Source | Kind | Priority | Endpoint |
| --- | --- | --- | --- |
| Models.dev | aggregator | 30 | <https://models.dev/api.json> |
| OpenRouter | route_api | 20 | <https://openrouter.ai/api/v1/models> |
| LiteLLM | aggregator | 40 | <https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json> |

The field vocabulary is `input_price`, `output_price`, `cache_read_price`,
`cache_write_price`, `context_window`, `max_output_tokens`, `tool_calling`, `vision`,
`reasoning`, `structured_output`, `open_weights`, and `release_date`. Not every
source provides every field. These feeds are observations for the caller's
validation and review policy, not direct authorization to overwrite facts.

Missing/null facts stay absent. Explicit zero prices and false capabilities remain
zero/false. Prices are USD per million tokens: Models.dev already uses that unit;
OpenRouter and LiteLLM per-token rates are multiplied by one million using decimal
arithmetic. Finite negative prices are preserved for the caller to quarantine
(including dynamic-pricing sentinels); they never become free. Nonnumeric and
nonfinite numeric observations reject the entire source snapshot. Limits must be
positive integral values. Token prices do not include request, image, audio,
service-tier, or context-threshold charges. A base price is not a total cost quote.

## Models.dev

The [maintainer's schema and field documentation](https://github.com/anomalyco/models.dev#adding-model-metadata)
identify `canonical_model_id` as the explicit originating model reference. The
adapter uses it when supplied. Otherwise it scopes the exact API identifier to
the serving provider. Identifiers retain case, version/date suffixes, and route
variants. No model-name similarity or guessed lab mapping is used.

Input modalities determine vision only when a nonempty modality list exists.
The actual `release_date` is retained at its stated precision (`YYYY-MM` or
`YYYY-MM-DD`); `last_updated` and knowledge cutoff never become release dates.

## OpenRouter

The [official models endpoint](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties)
provides route prices, context, output limits, architecture, and supported
parameters. The serving provider is always OpenRouter. `canonical_slug` is used
when present; otherwise the exact route stays OpenRouter-scoped. A `:free` or other
variant remains in `api_model_id` even if it shares an explicit canonical slug.

A supported `tools`, `reasoning`/`reasoning_effort`, or `structured_outputs`
parameter is positive evidence. Its absence is unknown. `response_format` alone
does not establish JSON-schema support. The adapter does not interpret `created`
as a model release date or infer open weights from a repository identifier.

## LiteLLM

The [official cost map](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json)
and [pricing documentation](https://docs.litellm.ai/docs/proxy/custom_pricing)
provide an independent, lower-priority community observation. Only chat/completion
entries with an explicitly mapped provider are imported. `sample_spec`, other
modalities, and unrecognized or deployment-specific provider namespaces are
excluded. The allowlist lives in `LITELLM_PROVIDERS`; extending it requires checking
the actual transport/API identifier relationship. In particular, Azure deployment
IDs and regional Bedrock routes are not guessed.

Only the exact known transport prefix is removed. Prefixed/unprefixed aliases for
the same route are consolidated: agreeing facts are retained and conflicting
facts become `rejected_fields: {field: [observed_values]}` for caller review.
Conflicts must never be silently chosen or treated as missing evidence.

`max_tokens` has legacy input/output semantics and is not imported.
`max_input_tokens` is an input ceiling rather than an unambiguous combined context
window and is also omitted. Explicit `max_output_tokens` is retained. Release
dates, open weights, and benchmark scores are not inferred.

## Source failures and manifests

`failures` is a list of `{source, error}` objects with sanitized exception types;
remote response bodies and arbitrary exception messages are not logged.
Malformed or empty snapshots fail atomically. Other sources continue.
The caller must preserve the last successful observations for every failed source;
a failed or absent feed is never evidence that routes were removed.

`manifests[source]` is `{count, hash, url}` for successful sources only. `count`
is the normalized record count; `hash` is SHA-256 of the complete received JSON
serialized with sorted keys, compact separators, and no nonfinite numbers.
The caller owns persistence, fetch timestamps, provenance, source precedence,
change detection, and approval/application policy.

## Official Hermes documentation monitoring

[Hermes' official documentation](https://hermes-agent.nousresearch.com/docs/)
links to `NousResearch/hermes-agent`. `fetch_harness_changes(fetcher=None)` reads
GitHub's commits API filtered to `website/docs` and returns the same three-part
tuple. Its record contains `entity: harness`, `name: Hermes Agent`, `source:
hermes-official-docs`, `source_kind: official_docs`, the API `source_url`, commit
`url`, `content_hash` (commit SHA), and `evidence` containing the SHA, timestamp,
first-line commit title, documentation URL, and path.

The caller stores the first revision as a baseline and sends later revision
changes to pending review. The monitor emits no capability fields and cannot
apply harness facts automatically. A documentation commit signals a need to
inspect the diff; it does not establish that any particular capability changed.
The source manifest hash is the commit SHA, not a hash of volatile API metadata.
Failures preserve the previous baseline. Public GitHub rate limits apply.

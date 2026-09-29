# UseThisModel data-quality audit — 2026-09-29

This report records the read-only baseline before the data-quality and freshness
changes. The SQLite integrity check passed and foreign-key check returned no
violations. The full test suite passed (`110 passed`).

## Baseline

| Measure | Count |
| --- | ---: |
| Canonical models | 3,322 |
| Provider routes | 9,329 |
| Providers | 240 |
| Active offers | 2 |
| Explicitly free routes | 658 |
| Benchmark datasets | 5 |
| Benchmark results | 3 |
| Pending review items | 2,788 |

The reported counts are real and internally consistent, but they overstate
identity quality and benchmark coverage. Most routes came from broad aggregator
catalogs, offers did not ingest OpenRouter endpoint promotions, and four of the
five benchmark definitions had no results.

## Identity and provider normalization

- Exact canonical-slug duplicates: 0.
- Case-folded canonical-slug duplicates: 11 groups / 22 rows.
- Case-folded canonical-name duplicates: 96 groups / 192 rows. A shared display
  name is not sufficient evidence to merge these records.
- Normalized provider duplicates: `Z.ai` / `Z.AI`, `DeepInfra` / `Deep Infra`,
  and `NovitaAI` / `Novita AI`. These splits cover 19, 215, and 245 routes
  respectively.
- Case-only route and provider-scoped alias duplicates: 4 groups / 8 rows,
  under Novita AI.
- Models containing `latest`: 110 by canonical name/slug (103 by slug in the
  independent audit); 191 route IDs and 191 aliases contain `latest`. These are
  moving aliases and must not silently become immutable model releases.
- The queue contains 144 ambiguous canonical-identity items. These are not safe
  automatic merges.

## Pricing, provenance, freshness, and capabilities

- 8,891 routes have both current input and output prices; 434 have no current
  price. Missing input and output counts are 438 each.
- 658 routes have explicit zero input and output prices and every one is marked
  free. Missing prices are not treated as free.
- 62 routes have an asymmetric zero price. These are mostly embedding, rerank,
  audio, media, and Perplexity billing shapes and require semantic handling.
- No negative current prices and no duplicate current price keys exist.
- Every route and current price has a source ID. However, 9,319 of 9,329 routes
  and 25,347 of 25,352 current prices are backed only by MEDIUM-reliability
  machine catalogs; only five current prices have HIGH first-party evidence.
- All route and current-price timestamps are from 2026-09-29, so none are older
  than seven days. A new fetch timestamp is not proof that the value changed.
- Missing context: 855; missing max output: 327; tool support unknown: 331;
  structured output unknown: 2,965; commercial use unknown: 9,319.
- 1,324 models have no release date. Only three release dates have official
  provenance; 1,989 are aggregator-sourced and the remainder unverified.

## Lifecycle, offers, and free routes

- All 3,322 models are marked active because the catalog has no effective
  offering-level lifecycle representation.
- Eight Azure routes disappeared from a successful LLM Gateway source snapshot.
  Their prior facts were correctly retained and queued; removal/deprecation is
  not yet confirmed.
- The two offers are valid and verified: OpenRouter Free Models Router and the
  provider-wide OpenAI Batch API discount. This is incomplete because the
  importer does not read OpenRouter provider endpoint variants or their
  `pricing.discount` field.
- OpenRouter route variants materially differ in price, provider tag, status,
  context, tools, structured output, and quantization. A single flattened
  OpenRouter model route cannot accurately represent promotions.

## Benchmarks

The five definitions are Artificial Analysis Intelligence Index 4.3.2,
LiveBench 2025-02, SWE-bench Verified, Terminal-Bench 2.0, and 3D Arena. Only
LiveBench has results (three); all are LOW confidence and lack model version,
harness, and evaluation date. They remain historical evidence and must be kept
out of current rankings.

Live publisher research confirms current versions including:

- Artificial Analysis Intelligence Index 4.3.2.
- Artificial Analysis Coding Agent Index 1.5, composed equally of DeepSWE 1.1,
  Terminal-Bench 4.0, and SWE-Atlas-QnA.
- Terminal-Bench 4.0.0 (66 tasks).
- LiveBench 2026-06-25.
- SWE-bench Pro V2 (642 public tasks); SWE-bench Verified remains a versioned
  500-task subset rather than a continuously overwritten score.

Coding and agent results require benchmark version, model/checkpoint or route,
harness/scaffold and version, reasoning setting, policy/budget, grader, and
evaluation date. Costs and token usage belong to that result configuration.

## Review queue triage

| Class | Count | Policy |
| --- | ---: | --- |
| Within-source conflicts | 1,317 | Preserve; source aliases disagree. |
| Quarantined invalid/legacy values | 752 | Safe to close only when quarantine and retained selected fact are verified. |
| Cross-source or extreme-price conflicts | 556 | Preserve for evidence review. |
| Model alias ambiguity | 144 | Preserve; never fuzzy-merge. |
| Possible route removals | 8 | Preserve until lifecycle evidence exists. |
| Other legacy release gaps | 7 | Preserve until official announcement evidence exists. |
| Benchmark evidence gaps | 3 | Preserve; exclude from current rankings. |
| Harness source changed | 1 | Preserve for capability interpretation. |

The first deterministic auto-resolution target is the already-quarantined
invalid/legacy class, after checking that no rejected observation is selected.
Provider normalization is safe only through explicit mappings and foreign-key
remapping. Case-folded model identity, `latest` aliases, genuine source
disagreements, and route disappearance remain ambiguous.

## Test gaps to close

- Case-insensitive provider/canonical/alias normalization regressions.
- Route-specific OpenRouter endpoint discounts and exact zero-price free routes.
- Missing price never becoming free.
- Route lifecycle and freshness thresholds.
- Current versus historical benchmark versions and required harness metadata.
- Source-health attempt/success/error accounting.
- Review triage classification and deterministic resolution.
- Quality metric calculations against the production-shaped snapshot.

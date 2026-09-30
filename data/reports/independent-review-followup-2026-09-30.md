# Independent review follow-up — 2026-09-30

This report records the current catalog after the V2 work already in progress
and the follow-up changes in this task. Compatibility and review-queue counts
come from the published catalog snapshot loaded into a temporary database.

## Compatibility

| Measure | Current |
| --- | ---: |
| Harness/provider rows with an explicit supported mode | 4 |
| Route-specific evidence rows / distinct routes | 8 / 6 |
| Workflow/harness compatibility rows | 182 |
| Harnesses with explicit provider rows | 3 / 14 |
| Harnesses with documented OpenRouter access | 13 / 14 |
| OpenRouter routes eligible for the evidence-derived rule | 488 |
| Derived harness/route results other than UNKNOWN | 5,892 / 6,344 |

The new derivation only applies when the harness has a source-backed
`OPENROUTER=YES` access method and the offering is an exact OpenRouter route.
It reports route tool support as recorded, MCP capability separately,
configuration as required, reliability as UNKNOWN, and both harness and route
sources with their verification dates. Claude Code is restricted to Claude
models, consistent with its documented gateway limitation. Unknown providers,
protocols, models, and unsupported workflows continue to resolve to UNKNOWN.

Direct-provider protocol-derived coverage remains unimplemented because the
catalog has no provider protocol evidence table. Treating every OpenAI-shaped
endpoint as equivalent would overstate support. In particular, Codex requires
Responses protocol support; generic Chat Completions is insufficient.

## Access and filters

| Measure | Before | After |
| --- | ---: | ---: |
| Routes previously called FREE from zero token prices | 658 | — |
| Reclassified as subscription-included | — | 205 |
| Routes counted as publicly free | 658 | 453 |
| Zero token price facts retained | 658 | 658 |
| Public FREE_API routes with tools | — | 370 |

The zero token price is preserved as a pricing fact. Route access is now a
separate semantic field. Free + Tools excludes subscription-branded endpoints;
the separate Included with subscription filter, API field, and MCP tool expose
the paid-plan requirement. Friendly context inputs normalize to token counts;
malformed numeric, harness, and workflow filters return an explicit warning or
web error message instead of silently broadening the result.
Subscription-included rows also store legacy `free_status=PAID`, preventing
older clients from treating them as public free routes.

## Provider offers

The catalog has 119 active offers: 118 OpenRouter offers and one first-party
OpenAI Batch API discount. No new active provider promotion was imported. The
official Alibaba Model Studio pricing page currently labels Qwen 3.7 prices as
limited-time discounts, but its different regions, context tiers, day/night
rates, and missing end date do not support one safe normalized promotion record.
The current evidence is at
<https://www.alibabacloud.com/help/en/model-studio/model-pricing>.
Provider-promotion discovery adapters remain outstanding; known `ends_at`
values continue to expire through the existing offer lifecycle.

## Review queue

Pending queue total: **2,044** (unchanged).

| Triage class | Pending |
| --- | ---: |
| Within-source conflict | 1,317 |
| Source disagreement | 563 |
| Identity ambiguity | 144 |
| Possible route removal | 8 |
| Release evidence gap | 7 |
| Benchmark evidence gap | 3 |
| Harness change | 2 |

The largest source groups are models.dev (1,626 row/source associations),
LiteLLM's GitHub price catalog (541), and OpenRouter (420). The 144 identity
ambiguities remain unresolved because their candidates include different
provider IDs; no fuzzy or cross-source auto-merge was made. Same-source queue
consolidation remains outstanding.

## Public operations and security

The current docs and deployment helpers replace the previously committed
production host, SSH port, server account, Coolify application/volume IDs, and
private filesystem examples with placeholders/private configuration. Those
details were already present in Git history; history was not rewritten.

The credential-pattern scan covered 44 reachable commits and found no AWS,
Google, GitHub, OpenAI-format API keys, or private-key headers. The current
working tree scan found no credential patterns. This is a pattern scan, not a
proof against every possible secret encoding.

## Verification

- Data validation: pass (integrity, foreign keys, prices, limits, free-route
  consistency, release dates, current-price uniqueness, offer verification,
  OpenRouter variants, model identity).
- SQLite `PRAGMA integrity_check`: `ok`.
- Full pytest and Ruff results are recorded in the task completion summary.

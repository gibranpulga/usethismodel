# UseThisModel V2 final audit — 2026-10-01

## Scope and outcome

Audited the current `main` branch, the production deployment at [usethismodel.com](https://usethismodel.com), its persistent catalog, public API and remote MCP endpoint. Browser QA covered the requested 16 page groups at 1440, 1024, 430 and 390 px. The audit found and fixed API latency, search interpretation and API filter validation defects, plus missing security headers on the ASGI/MCP path. No unrelated product feature was added.

### Findings

- **HIGH — fixed:** `/api/v1/models?limit=1` loaded every provider route before paging. Independent production probes measured 4.8–10.59 seconds (ETag 304 revalidation still took 6.19 seconds). The handler now pages canonical models first and fetches routes only for that page.
- **HIGH — fixed:** MCP and ASGI rate-limit responses bypassed Flask security headers. An outer ASGI middleware now sets HSTS, CSP, `nosniff`, referrer/permissions policy and `noindex` for MCP, including 429 responses.
- **HIGH — fixed:** direct DeepSeek V4.1 Flash and V4 Pro prices were sourced from aggregator feeds and omitted the official peak/off-peak schedule; V4 Pro’s current off-peak amount was also inconsistent with the official page. Superseded those route prices with dated first-party observations, recorded their peak rates in price notes, and expired an unsupported zero cache-write price. Price-source classification now recognizes the catalog’s `official pricing` source type.
- **MEDIUM — fixed:** malformed boolean/status filters were silently converted to false or “all”; unknown harnesses in API search returned empty results with HTTP 200. These now return HTTP 400 with explicit `invalid_filter` errors.
- **MEDIUM — fixed:** natural-language search aliases (for example `gemini`, `works with Hermes`, and `OpenCode Unreal MCP`) were parsed by the finder but dropped in API/MCP route search. That could show unrelated catalog-wide results. The shared API and MCP paths now apply interpreted facets and expose them in API metadata; known unsupported harnesses return zero results.
- **MEDIUM — fixed:** the first production dogfood pass found `OpenCode Unreal MCP` returned 713 routes, including 83 with tool support `NO` and 16 `UNKNOWN`. Natural-language MCP workflow interpretation now also requires affirmative tool support; this matches the dedicated workflow finder and reduces the result set to the 614 tool-capable routes.
- **MEDIUM — remaining data coverage limitation:** official exact-route pricing is sparse: the 2026-09-30 pricing trust review found 10 exact-provider-priced routes and 422 aggregator-only routes in its curated comparison scope. API output distinguishes source class; sampled prices were checked against provider sources.
- **MEDIUM — remaining data coverage limitation:** 130 model rows retain `identity_kind=UNKNOWN`, 80 duplicate display-name groups remain intentionally unmapped without exact identity evidence, and 144 pending review rows explicitly concern canonical identity. The full pending review queue contains 2,055 items.
- **MEDIUM — remaining data coverage limitation:** current benchmark rows cover 20 models; most benchmark result configurations are not directly comparable. The UI/API state comparison constraints. No cross-benchmark scalar “best model” score was found.
- **LOW — remaining documentation limitation:** OpenAPI paths are generated from Flask routes and are current, but its parameter, response and error schemas are sparse compared with the public API documentation.

## Catalog integrity and coverage

Production and the checked-in catalog report the same catalog snapshot digest. SQLite `quick_check` passed; snapshot chunk hashes, ID uniqueness and the audited foreign-key relationships passed validation.

| Measure | Current value |
|---|---:|
| Canonical model records | 3,306 |
| Active provider routes | 9,329 |
| Canonical provider entities | 237 (3 aliases) |
| Model alias rows / identity redirects | 9,315 / 16 |
| Unknown model identity rows | 130 |
| Duplicate case-folded display-name groups | 80 (kept separate where evidence does not prove identity) |
| Current pricing records / archived price observations | 25,368 / 1,681 |
| Routes with official input/output price evidence / aggregator-observed price evidence | 15 / 8,880 |
| Plans | 23 |
| Active offers | 121 |
| Public free API/free-tier routes | 453 |
| Public free API/free-tier routes with tools | 370 |
| Benchmark datasets / current datasets | 10 / 6 |
| Benchmark result rows | 179 |
| Models represented by current benchmark results | 20 |
| Harnesses / workflows | 18 / 7 |
| Pending review rows (all subjects) | 2,055 |
| Pending canonical identity review rows | 144 |

All provider routes were active in the production sample. Free access is separated from `INCLUDED_WITH_SUBSCRIPTION`; 205 subscription-included routes are not counted as free. There are 10 offers with unknown status, excluded from the 121 active offers. The 117 active OpenRouter endpoint promotion rows identify inferred reference prices in the offer text/data; an ordinary low route price is not itself classified as a promotion. Expirations marked unknown remain unknown.

Release records with dates are mainly aggregator-backed: 1,979 are labelled aggregator, 4 official and 6 unverified in the current catalog. Release date provenance is present and chronological ordering is used. Source-health readiness reported 5 healthy checks and no failing or documentation-source checks.

### Provider price spot checks

Provider documentation was compared with exact model/price fields in the catalog, including input, output, cache and tier units where published. OpenAI GPT-6.1 Sol, Anthropic Claude Sonnet 5, Google Gemini 3.8 Flash, Z.ai GLM-5.3, Alibaba Qwen3.8 Max, Mistral Large 3, MiniMax M3 and its annual Token Plan matched the sampled first-party values. The DeepSeek V4.1 Flash and V4 Pro direct routes did not: the aggregator feed represented off-peak rates without the schedule, and V4 Pro values differed. Their first-party schedule is now authoritative in the catalog; off-peak rates are shown with explicit peak values, and unpublished cache-write pricing is unknown. MiniMax context tiers, DeepSeek peak/off-peak pricing, Google Batch/cache tiers and Z.ai cached-input promotion were checked separately; where dynamic schedule or promotional terms apply, a single undifferentiated price would be misleading.

Sources: [OpenAI model pricing](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [Anthropic API pricing](https://platform.claude.com/docs/en/about-claude/pricing), [Google Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing), [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/), [Z.ai pricing](https://docs.z.ai/guides/overview/pricing), [Alibaba Model Studio pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing), [Mistral pricing](https://docs.mistral.ai/inference/pricing), [MiniMax pricing](https://platform.minimax.io/subscribe/token-plan?tab=api-enterprise). Moonshot/Kimi exact first-party route pricing was not in the official-price comparison subset; those routes must be treated as aggregator-observed or unknown until first-party evidence is recorded.

## Compatibility

The production API was queried for Codex CLI, Claude Code, OpenCode, Pi, Hermes Agent, Cline, Roo Code, Continue, Aider, Goose, Qwen Code, Gemini CLI, Zed and newer harnesses. It returns compatible route records for the documented integrations and returns no matches for Gemini CLI, Amp, Cursor CLI, Factory Droid and Junie CLI where current route evidence is absent. This does not infer incompatibility; the absence remains unknown. Route-level evidence and provider/harness protocol evidence are distinct from subscription access.

OpenRouter routes, direct API route records, custom OpenAI-compatible endpoint declarations, subscription-included access and MCP workflows were inspected. Production query examples returned 692 Hermes-compatible routes, 713 OpenCode routes and 614 OpenCode + Unreal Engine MCP routes. REAPER MCP is a recorded workflow. A route is only shown for a recorded compatible/configuration/partial state; unsupported or unknown combinations are not promoted as compatible.

## Benchmarks, plans and offers

The catalog contains LiveBench, SWE-bench Verified/Pro, Terminal-Bench and Artificial Analysis datasets. Some current dataset entries have metadata but no result rows. Current result rows are limited to 20 models; incomplete harness/scaffold settings remain explicit. Comparisons require a shared benchmark version, metric, task and configuration. No global cross-benchmark rank or unsupported universal best score was found.

Twenty-three plans retain source URLs, access distinctions, verification dates and provider terminology for non-comparable allowances. Current promotions remain separated from route prices and subscription-included access. Expired promotions are excluded from current offers; unknown expiry/status is not represented as confirmed current.

## API and MCP

Public read-only API v1 endpoints verified: `/api/v1`, `/models`, `/models/{canonical-slug}`, `/providers`, `/plans`, `/access-routes`, `/harnesses`, `/workflows`, `/offers`, `/free-routes`, `/releases`, `/benchmarks`, `/compatibility`, `/search`, and `/openapi.json`. Pagination, page/offset exclusivity, capped limits, invalid filters, source URLs, freshness fields, cache headers and error behavior were exercised. Collections return `data` and `meta`; malformed filters now produce explicit 400 errors.

The remote streamable HTTP MCP server initializes successfully and exposes 17 tools. Dogfood calls covered Hermes cost/tool filtering, OpenCode + Unreal workflow, free tool routes, route comparisons, benchmark evidence, current promotions and cost calculation. Tool outputs include page cursors and source/freshness fields; compatibility scans are not capped at an arbitrary first ten thousand routes. Every tool declares read-only annotations, and MCP database connections use SQLite `query_only`.

## Frontend, search and discovery

The production browser pass rendered all 16 requested page groups at 1440, 1024, 430 and 390 px (64 renders): all returned HTTP 200; there was no document-level horizontal overflow, broken image, missing main H1, unscoped table header, unlabeled form field or recorded layout shift. Dense deal/benchmark/ranking tables scroll inside their own containers on narrow widths; models switch to route cards. Mobile navigation, visible keyboard focus and dark mode passed. The home page shows active offers first, then dated releases, task finder, site activity and route coverage. Screenshots are saved under `/tmp/utm-v2-audit/postdeploy/`.

Search spot checks returned matching results for GLM, GLM 5.3, DeepSeek, free tools, cheap coding, 1M context tools, 3D, image and video generation. “New this week”, deals and harness/workflow facets map to explicit date, active offer and compatibility filters. The API/MCP interpreted search correction prevents empty-query fallback and includes the applied interpretation in API metadata.

Production serves server-rendered useful content, canonical URLs, OpenGraph and JSON-LD. `/robots.txt`, `/llms.txt`, `/llms-full.txt`, `/sitemap.xml`, OpenAPI and MCP docs were reachable. OAI-SearchBot and normal search crawlers are allowed; GPTBot, ClaudeBot and Applebot-Extended are blocked under the current training-crawler policy. Query URLs are disallowed from crawling, and API/internal routes carry noindex policy.

## Performance and security/operations

Before the fix, independent production measurements for `/api/v1/models?limit=1` ranged from 4.8 to 10.59 seconds; an ETag 304 still took 6.19 seconds. The optimized local production-data path measured 11 ms for one model and 56 ms for 100 models. After deployment the same API request took 204–240 ms in repeated probes (about 20–44× faster than the previous range). Representative post-deploy requests: homepage 1.13 s, `/models` 1.13 s, filtered models 0.34 s, compatibility 0.73 s, OpenCode harness 0.91 s, model search 0.63 s, API search 0.47 s, API model page 0.24 s; broad paged model response stayed 2.4 KB. API list routes returned in 0.20–0.99 s. These are single-run wall-clock observations, not a load test.

Representative pre-deploy requests: homepage 0.72 s, `/models` 1.26 s, robots 0.42 s, sitemap 0.23 s, OpenAPI 0.29 s and MCP info 0.87 s in the independent browser/API probe. API collections use 60-second shared caching; rate limits are 120 requests/minute for the public API and 60/minute for MCP. Flask pages provide CSP/HSTS/nosniff/referrer policy; the audit added the same needed headers around ASGI/MCP and limiter-generated errors. Internal dashboard access without credentials returned 404. Git-history secret-pattern review found no committed credentials; dedicated gitleaks/trufflehog binaries were unavailable.

The daily updater workflow uses a nonblocking lock, SQLite online backup, isolated staging/worktree, catalog/source validation, lint/tests and a data-only commit gate; deploy/readiness is explicit. The first safe `--dry-run` on the pre-audit branch completed source update and data validation, then stopped at pytest (exit 2): the updater virtual environment was missing pinned requirements, including MCP, so test collection failed. Installing the repository's pinned requirements in the isolated updater environment fixed collection. The retry against the audited commit passed source update, data validation, pytest and Ruff, then reported “dry run completed; no artifacts or commits”; staged and pending state were removed, and the live database was not modified. A verified pre-deploy SQLite backup is stored privately under `~/.config/coolify/backups/usethismodel-20261001/`.

## Verification and deployment

- `ruff check .`: pass.
- Full pytest suite after the MCP workflow filter fix: 298 passed in 153.35 seconds; `ruff check .` passed.
- SQLite local and production backup `quick_check`: `ok`; foreign-key errors: 0; all 308 catalog snapshot chunk hashes matched.
- Production readiness: `ok`; 3,306 models, 9,329 routes, 5 healthy source checks and 0 failed sources.
- Deployment: Coolify deployment `20fxskccshzsxfby6mzlufyp` finished healthy on commit `16a27fe655ac139441edd93564e78236971b4382`.
- Production HTTPS smoke checks: homepage, core API collections, feeds, MCP initialize/tools, `/health`, `/health/readiness`, `/robots.txt`, `/llms.txt`, `/llms-full.txt`, sitemap and OpenAPI returned 200. Malformed API filters returned 400. CSP, HSTS, `nosniff`, referrer/permissions policies and MCP noindex were verified.
- Remote MCP dogfood: all 17 tools are read-only; Hermes tool-route pagination returned distinct adjacent pages; the initial OpenCode + Unreal Engine MCP query returned 713 routes, including 99 without affirmative route tool support, and is now corrected in code/tests to match the 614-route explicit compatibility filter; DeepSeek V4 Pro returned first-party input/output/cache-read evidence, source URL, observation date and peak-rate notes; free-route, deal, benchmark and cost queries returned structured results.
- SSR/crawling: JavaScript-disabled HTML retained headings and body content; filtered URLs are `noindex,follow` with clean canonicals; OAI-SearchBot, Googlebot and Bingbot are allowed, while training bots follow the existing deny policy.

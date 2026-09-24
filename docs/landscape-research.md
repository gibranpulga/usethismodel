# Model discovery landscape and data sources

Research captured 2026-09-24. This is a product and source assessment, not a
license opinion. Before redistributing third-party datasets, check current API
terms, licenses, attribution rules, and provider branding requirements.

## Products reviewed

| Product | What it does well | Exposed information and useful UX | Gap UseThisModel can address |
| --- | --- | --- | --- |
| [PricePerToken](https://pricepertoken.com/) | Fast, broad LLM discovery; practical filters, calculator, release feed | Provider/model, input/output/cache prices, context, modalities, tools, reasoning, benchmarks, open-source labels | Make provider route identity and route-specific caveats explicit; include plans/deals and harness compatibility with evidence |
| [Models.dev](https://models.dev/) | Clean developer catalog and a useful model/provider distinction | Model facts, provider serving records, limits, modalities, capabilities, pricing; searchable catalog | Does not answer which harness and offer make a route useful for a task; community-maintained metadata needs provenance |
| [OpenRouter directory](https://openrouter.ai/models) | Convenient unified route discovery and filtering | Model metadata, endpoint/provider details, price, context, modalities, parameters and popularity; free and discount collections | Data describes OpenRouter routes; popularity is not quality, and external provider plans/harness support are outside scope |
| [LiteLLM model catalog](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) | Broad machine-readable provider/model cost map | Provider/model keys, pricing, context and capability metadata | Gateway-oriented best-effort data can lag or need overrides; no decision UX, harness matching, or offer comparison |
| [Artificial Analysis](https://artificialanalysis.ai/) | Transparent independent measurement and latency/cost comparisons | Evaluations, speed, time-to-first-token, prices and stable model identifiers; API available | Not a harness/route planner; public reuse must follow attribution and data terms |
| [LiveBench](https://livebench.ai/) | Fresh questions, objective scoring and task-specific leaderboards | Reasoning, math, coding, language, data analysis and instruction-following scores; public code/data | Results need task/version/date/method context and do not by themselves prove a route works in an agent |
| [Scale SEAL](https://labs.scale.com/leaderboard) | Expert-designed coding and agentic evaluations | Coding/frontier leaderboards and task scores | No public redistribution API/license established in this review; link out unless permissions are clear |
| [Epoch AI](https://epoch.ai/benchmarks) | Curated benchmark data and useful downloadable/API data | Benchmark runs and model data with source metadata | External benchmark content can retain separate rights; preserve per-row source and license |
| [LLM Stats](https://www.llm-stat.com/) | Broad multi-dimensional discovery | Reasoning, coding, agent, arena, context, speed, price and license comparisons | Aggregated scores need inspectable source/method; does not resolve route/harness compatibility |
| [Top3D](https://www.top3d.ai/leaderboard) | Modality-specific human preference/Elo comparison for 3D generation | 3D task categories, preference ranking and pricing | Useful future UX reference; no machine-readable API or clear redistribution terms found |
| [fal model catalog](https://fal.ai/models) | Strong media model catalog and developer invocation docs | Image/video/audio model endpoints, schemas, queue/streaming patterns, usage billing | Covers fal routes; not a cross-provider offer or harness comparison |

Other adjacent products include [LLM Pricing](https://llmpricing.dev/), [LLM
List](https://llm-list.com/), [WhatLLM](https://whatllm.org/), [ModelCompare](https://modelcompare.dev/),
[LLMCompare](https://llmcompare.dev/), and Vantage's model catalog. This makes
another flat price list a weak differentiator. The product opportunity is a
source-backed answer to: model + provider route + plan/deal + harness + task,
including why that whole path fits and what could break it.

## Candidate machine-readable sources

1. **Official provider APIs and pricing pages** are the authority for route
   prices, model availability, limits and terms. They often do not expose plan
   quotas or temporary offers in one feed. Keep source URL, checked time,
   currency/unit and constraints; manually review non-machine-readable offers.
2. **Models.dev** exposes [`api.json`](https://models.dev/api.json),
   [`models.json`](https://models.dev/models.json) and
   [`catalog.json`](https://models.dev/catalog.json), with useful distinctions
   between model facts and provider-served variants. It is community maintained;
   store source IDs and last-seen timestamps, and verify important claims.
3. **OpenRouter API** documents a model directory at
   [`/api/v1/models`](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties)
   and route-specific endpoint information. Treat it as evidence about its own
   routes, not every provider's direct API.
4. **LiteLLM's JSON model map** is broad and easy to import, but is best used as
   a backfill/check rather than billing authority. Its IDs and costs are shaped
   for gateway accounting and may lag or have custom overrides.
5. **Artificial Analysis API** provides measured performance and pricing with
   attribution requirements and authenticated access. Keep credentials
   server-side and cache results. Confirm the current data terms before public
   republication.

## Benchmark automation and record design

- LiveBench publishes code/data under Apache-2.0 for its benchmark suite;
  constituent datasets can have their own terms. Preserve each benchmark's
  source/license and the evaluation version.
- Epoch AI says its own data is CC BY with attribution, while benchmark
  questions/answers and external run data can carry their original licenses.
  Retain row-level provenance and license.
- Artificial Analysis allows API access under its API/data terms and attribution
  rules; verify reuse rights before mirroring scores.
- Scale SEAL and Top3D are useful references, but this review did not establish
  an API or a right to republish their rankings. Link out or request permission;
  avoid brittle scraping.

Store benchmark, task/version, metric, evaluation date, model/version,
provider/route when known, harness, prompt or harness method when available,
source URL and license. Do not collapse different measurements into an opaque
universal rank. Keep objective evaluations separate from subjective
recommendations.

## Product data distinctions

- Open weights and hosted API price are independent facts. A free route is a
  provider/offer fact with terms, limits and a checked date, never a universal
  model label.
- Tool/function calling is a route/model capability. MCP is primarily a
  harness capability. A working MCP flow also requires provider access, model
  availability, route tool support, adequate model tool-use behavior, and
  compatibility caveats.
- Recommendations should explain the evidence and fit; benchmark measurements
  remain separate from those judgments.

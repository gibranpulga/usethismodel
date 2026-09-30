# Canonical model identity V2 reconciliation — 2026-09-30

The V2 identity pipeline is populated with source-backed decisions. This report
is the before/after summary; the full row-level audit, exact provider evidence,
candidate routes, and duplicate-group classifications are in
`canonical-model-identity-audit-2026-09-30.json`.

| Measure | Before | After |
| --- | ---: | ---: |
| Canonical models | 3,322 | 3,306 |
| Provider routes | 9,329 | 9,329 |
| Duplicate canonical-name groups | 96 | 80 |
| Unresolved provider identities | 130 | 48 |
| Accepted explicit mappings | 0 | 82 |
| Pending explicit mappings | 0 | 0 |
| Pending identity reviews | 130 | 48 |
| Models merged | 0 | 16 |
| Routes preserved | 9,329 | 9,329 |

## Decisions

- 44 DeepInfra routes were mapped where the same exact provider model ID had
  one canonical target across observed routes.
- 38 routes were mapped using an exact OpenRouter canonical/upstream route ID
  to break an otherwise multi-target candidate set.
- Two duplicate canonical models were merged using an exact shared OpenRouter
  route ID. Fourteen more were merged through an exact source-backed alias to
  a unique OpenRouter-backed canonical model. Conflicting offer, alias, route,
  use-case, or media rows blocked a merge. Old model IDs and slugs redirect to
  retained models.
- The duplicate groups classify as A: 2 genuine duplicates merged; B: 14
  source-backed aliases merged; C: 3 explicit version/date groups retained;
  D: 77 unresolved duplicate-name groups. Matching names alone do not prove
  identity.
- 48 provider identities remain unresolved: 33 have multiple exact-ID targets
  without one OpenRouter canonical route to choose among them; 15 have no exact
  ID or exact-name candidate. Similar names are not used to merge them.

The reconciled catalog preserves all 9,329 provider offerings, all 26,983
pricing records, all three benchmark results, and all 129 offers. Identity
evidence is stored on accepted mappings with source, URL, evidence text,
confidence, and verification date. The unresolved audit includes Labs,
aliases, observations, OpenRouter endpoint variants, Models.dev and LiteLLM
sources, route candidates, and explicit ambiguity reasons.

## Family spot checks

Each row is one canonical slug in the published snapshot. The provider and
route totals were checked directly against its attached route rows; all listed
OpenRouter-backed families include their OpenRouter route under the same slug.

| Family / canonical slug | Providers | Routes | OpenRouter routes |
| --- | ---: | ---: | ---: |
| OpenAI `openai/gpt-oss-120b` | 50 | 78 | 2 |
| OpenAI `openai/gpt-5.4` | 43 | 47 | 1 |
| Anthropic `anthropic/claude-sonnet-4-6` | 43 | 52 | 1 |
| Google `google/gemma-4-31b-it` | 43 | 51 | 2 |
| DeepSeek `deepseek/deepseek-v4-flash` | 54 | 71 | 1 |
| Z.ai `zhipuai/glm-5.3` | 68 | 91 | 1 |
| Qwen `alibaba/qwen3.8-27b` | 41 | 48 | 2 |
| Mistral `mistral/mistral-large-3` | 2 | 2 | 0 |
| Kimi `moonshotai/kimi-k3` | 75 | 101 | 1 |
| MiniMax `minimax/MiniMax-M3` | 42 | 47 | 1 |

These checks confirm provider routes are grouped under the published canonical
slug. Separate versioned IDs, moving aliases, and provider-scoped unknowns
remain distinct where the available evidence does not establish equivalence.

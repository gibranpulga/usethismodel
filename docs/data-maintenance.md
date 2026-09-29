# Deterministic maintenance policy

The updater normalizes structured feeds, records observations, resolves accepted
facts, validates the candidate database, then exports it. Fetches are isolated;
a failed source cannot erase its previous observations. A missing field cannot
replace a known value. Prices and route capabilities are keyed by provider plus
exact API identifier. OpenRouter and direct-provider prices are separate routes.

## Precedence and evidence

Lower numbers win; source names break equal-priority ties deterministically:

- Official announcement: 5 (release evidence).
- Official provider / official documentation: 10.
- Official structured metadata: 15.
- OpenRouter's own route API: 20.
- Models.dev: 30.
- LiteLLM: 40.
- Other aggregators: 60.
- Unverified legacy data: 90.

Adapters cannot assign their own authoritative rank: the resolver owns it.
The current public catalog adapters do not claim to be official direct-provider
pricing. Future official adapters can outrank aggregators for the same route.
Benchmark observations are only authoritative when from that benchmark publisher;
no current catalog adapter imports benchmark scores. Unsupported benchmark fields
are quarantined. Existing seeded scores lack result-level evidence, so they are
preserved with manual-review items, not silently presented as newly verified.
A publisher homepage is insufficient evidence for a score or a massive revision.

Every distinct observation keeps its URL, source, value, timestamp, evidence and
acceptance flag. The selected-facts table links the displayed value to its winning
observation. Disagreeing current sources produce a discrepancy in the daily report
and a deduplicated pending review item. Within-source disagreement is quarantined.
Historical prices retain validity intervals. Changes in source precedence update
provenance even when the numeric price agrees.

`first_seen_at` records discovery; it is never copied to `released_at`. Release
metadata retains day or month precision and is marked `official`, `aggregator`, or
`unverified`. Existing seed dates without per-value evidence remain review items.
A model can have no release date even when it was just discovered. Canonical IDs
and known provider aliases are used exactly; similar names never trigger a fuzzy
merge. Ambiguous duplicate identities go to review.

## Gates

- Nonfinite or malformed source numbers fail that source; negative prices remain
  rejected evidence and cannot become zero.
- Both explicit input and output prices must be zero for a free route.
- Context/output limits must be positive integers no larger than 100 million.
- A catalog or known provider collapse over 25%, over 25% loss of priced routes,
  or a previously paid provider becoming at least 95% zero-priced is quarantined.
- Unexplained price increases above 10x are held for manual review.
- SQLite integrity, foreign keys, all stored prices, limits and free-route claims
  are checked before publication and again when applying the snapshot.
- A total source outage or total quarantine fails the command. Sanitized failure
  reports preserve the review/rejected evidence; production stays unchanged.

A missing route is not proof of expiry. Large disappearances fail safety gates;
smaller removals retain the last known evidence pending later source confirmation.
Free-route expiry is reported when accepted prices cease to be zero. Offers with
explicit passed end dates expire deterministically; no subscription/offer page is
scraped and no new offers are invented. The report contains all requested sections,
including sections with no changes.

## Review and Hermes

Each pending item has entity, proposed change, current/proposed value, sources,
evidence, confidence, reason, status and stable ID. The daily update does not invoke
Hermes. The installed VPS Hermes CLI supports noninteractive prompts and safe-mode
flags, but these alone do not prove a read-only, secret-isolated review boundary.
Automatic Hermes execution is intentionally disabled. Human/explicit optional
Hermes review may interpret duplicate identities, conflicts, subscription changes,
model summaries and harness documentation; it must not silently rewrite facts.
No Hermes configuration or secrets are copied into the repository or reports.

Review completion is an explicit maintenance operation: preserve its evidence,
record the accepted source observation, and mark the queue item resolved before
regenerating a snapshot. No UI feature or automatic LLM approval path is added.


Snapshots use a small catalog manifest and checksummed 1,000-row JSON shards.
This bounds individual Git file size as observations grow and keeps changes
reviewable at row level. Deployment verifies every shard before its transaction.
Legacy invalid prices/limits are quarantined with original row evidence before
validation; this corrects the previous importer's negative dynamic-price sentinels
and zero limits without losing the evidence.

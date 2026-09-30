# Data maintenance verification — 2026-09-29

The scheduled wrapper completed source updates, validation, pytest,
Ruff, data-only Git commits/pushes and an explicit Coolify deployment trigger.
The resulting commit deployed successfully and the running image matched that
commit and was healthy. The final documentation-only commit is deployed and
verified separately at completion of this stage.

## Installed schedule

The updater account's actual crontab contains:

```cron
20 5 * * * <updater-root>/repo/scripts/daily-update.sh >/dev/null 2>&1
```

The server timezone is configured locally. Cron is active. The job follows local
server time through seasonal clock changes.

The real wrapper was invoked while an independent process held its lock. It
returned successfully without creating a new run log or starting an update.
The lock also remained held across code refresh and scheduler re-execution.

## Changes observed during manual runs

| Report | New model records | New offerings | Price increases | Price reductions | Newly recognized free routes | New review items |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| [Initial refresh](../data/reports/2026-09-29-1c922e4745ef.md) | 846 | 940 | 262 | 58 | 658 | 2,752 |
| [Repeat verification](../data/reports/2026-09-29-42856deac74c.md) | 0 | 0 | 42 | 34 | 0 | 17 |
| [Final refresh](../data/reports/2026-09-29-be5ba9e3c26a.md) | 0 | 0 | 0 | 3 | 0 | 6 |

Price counts are field-level change events, including legacy-data corrections,
not counts of unique models or official provider announcements. Structured
sources can change between live runs. All three successful reports recorded
zero source failures. Historical failed-run reports remain in private updater state.

The live database contains 3,309 models, 9,296 provider offerings, 103,814
observations and **2,775 pending review items**. See
[the pending queue](../data/pending-review.json). Review categories include source
conflicts, inconsistent per-route canonical metadata, invalid legacy values,
ambiguous duplicate identities, seven legacy release dates and three legacy
benchmark scores without result-level publisher evidence.

## Checks and recovery

- 82 offline tests pass, covering precedence, repeatability, missing/null values,
  rejected evidence, catalog/pricing collapse, mass-zero changes, release dates,
  free-route correctness, snapshot checksums/rollback, dry-run isolation,
  publication safety, secret handling and snapshot replacement performance.
- Ruff, shell syntax and Git whitespace checks pass.
- Live SQLite integrity, foreign keys, prices, limits, free routes and release-date
  validation pass; migrations 1–7 are applied. No negative prices or invalid
  nonpositive limits remain in displayed records.
- All 14 checked HTTPS routes returned 200, including `/health`, `/models`,
  `/providers`, `/harnesses`, `/compatibility`, `/offers`, `/new-releases`,
  `/benchmarks`, `/use-cases`, `/compare`, `/calculator`, a free/tools filter and
  a model detail page. Certificate verification remained enabled.
- Two snapshot digests in the persistent database confirmed data survived
  container replacement. Individual snapshot shards are below 425 KB.
- Identical-input tests leave snapshot bytes unchanged. Reports alone do not
  create commits. Real live runs above had meaningful changes; no empty commit
  was created.

The first real run rejected old negative dynamic-price sentinels and zero limits.
They were moved into quarantined observations with original evidence before the
valid candidate was published. An overlapping code push was rejected by Git;
its data-only checkpoint was preserved, rebased without force-pushing, validated,
and retried. A subsequent snapshot replacement exceeded startup health timeouts
because parent-first deletion caused excessive foreign-key scans. Coolify kept
the healthy previous container and SQLite rolled back the incomplete transaction.
Child-first deletion, parent-first insertion and a regression test fixed that
case; the final replacement deployed successfully. The health probe now reads the
real schema, and future staging runs reconcile the latest published snapshot so
failed deployments cannot drop already-published observations.

## Sources, secrets and Hermes

Models.dev, OpenRouter and LiteLLM are public structured inputs. Official Hermes
documentation commits are monitored through GitHub's API. The first revision is
only a baseline; later revisions create interpretation review items.

Hermes is installed and has noninteractive/safe-mode CLI flags. Automatic LLM
review remains disabled because those flags alone do not establish an isolated,
read-only review boundary. Normal daily updates make no LLM calls and need no
model API keys.

Git uses a repository-scoped SSH deploy key. Coolify uses a separate deploy-only
credential loaded from a mode-0600 private file; neither credential enters cron,
Git, reports or logs. Logs rotate at 2 MiB, with bounded retained files/age.
Consistent SQLite backups retain at most 30 files/30 days. Historical reports are
preserved. The server had 67 GiB available during verification.

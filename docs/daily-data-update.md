# Daily data refresh operations

The server runs `scripts/daily-update.sh` as the `deploy` user. It takes a
nonblocking `flock` for the whole refresh, creates a consistent SQLite backup,
reconciles the latest published snapshot into a private staging database, updates
it in an isolated Git worktree, validates the data, runs
pytest and Ruff, and pushes a data-only commit to `main`. An explicit deploy-only Coolify API call
builds that commit; application startup applies its
versioned catalog snapshot to the persistent database.

Production database writes happen only in application startup after deployment.
The scheduler opens the source database read-only through SQLite's online backup
API, so it includes committed WAL data without copying an inconsistent database
file. Database bytes go directly to a private file, never terminal output or Git.
The backup uses Python in the healthy application container as UID 10001.
It requires exactly one healthy container mounting the expected named volume;
a deployment overlap safely postpones the refresh if the choice is ambiguous.

## Server layout and provisioning

- SSH: `ssh -p 7382 deploy@169.58.143.172`
- Server timezone: `Europe/Berlin`
- Root: `~/usethismodel-updater`
- Dedicated clean checkout: `~/usethismodel-updater/repo`, branch `main`
- Python environment: `~/usethismodel-updater/.venv`
- Private state, staging database, worktree, logs and backups: `~/usethismodel-updater/state`
- Application: `ild8duzk51xnfcuyxtyclzpg`
- Volume: `ild8duzk51xnfcuyxtyclzpg-usethismodel-data`
- Database in that volume: `/data/usethismodel.sqlite3`

The account needs Git, Python 3.12+, `flock`, Docker group access, and an SSH
credential authorized to push this repository. The SSH host key must already be
verified and known. Git is noninteractive (`BatchMode=yes`); authentication
failures stop the run. Do not embed tokens in the remote URL or cron entry. The deploy-only Coolify credential is stored at `state/coolify-deploy.json` with
mode 0600. It is loaded by the Python helper, sent only in an Authorization header
to the local API, and never enters command arguments, Git, reports or logs. The
helper hardcodes the UseThisModel application UUID. Coolify tokens are team-scoped;
this token has only the deploy ability, without read/write/root/sensitive access.
It has no automatic expiry; rotate it deliberately and replace the private file.
An explicit trigger is required because the configured auto-deploy setting did
not produce deployments during verification.

Provision once as `deploy` after preparing its GitHub authentication:

```sh
umask 077
mkdir -p "$HOME/usethismodel-updater/state"
git clone --branch main git@github.com:gibranpulga/usethismodel.git "$HOME/usethismodel-updater/repo"
python3 -m venv "$HOME/usethismodel-updater/.venv"
"$HOME/usethismodel-updater/.venv/bin/pip" install -r "$HOME/usethismodel-updater/repo/requirements-dev.txt"
```

Dependencies live outside the checkout and must be reprovisioned when requirements
change. The scheduler does not install arbitrary dependencies on every run.
Use the wrapper for manual invocations so they share the cron lock:

```sh
"$HOME/usethismodel-updater/repo/scripts/daily-update.sh" --dry-run
"$HOME/usethismodel-updater/repo/scripts/daily-update.sh"
```

Install this line in the **deploy user's** crontab after the first real run passes:

```cron
20 5 * * * /home/deploy/usethismodel-updater/repo/scripts/daily-update.sh >/dev/null 2>&1
```

This is 05:20 Europe/Berlin on the configured server, outside the clock-change
hour. Verify `HOME` if the account uses a different home directory, and use that
absolute path in cron. Preserve unrelated entries with `crontab -l` before
editing. `UPDATER_ROOT` may override the layout for another environment.

## Publication and failure recovery

The main checkout must be clean, on `main`, and never locally ahead of
`origin/main`. Each run fetches and fast-forwards it; local changes or divergence
stop the job without discarding work. Updates run in a detached worktree, so
failed imports/tests cannot dirty the main checkout. Only `data/` is staged.
Changes to `catalog.json` or `pending-review.json` justify a commit; a new report
alone does not. Identical catalogs and review queues produce no commit or deploy.

Before pushing, the job saves its commit hash in `state/pending.json` and retains
the validated staging database and worktree. If the push fails, the next real
run revalidates and retries that same commit. It does not force-push or discard
an unpushed automation commit. If remote `main` diverges, resolve that checkpoint
manually after inspecting its report and Git diff; the job fails closed. A dry
run with a pending commit also stops, because retrying it would publish changes.
Do not delete `pending.json` to make an unexplained failure disappear.

Inspect the latest files under `state/logs/` after any failure. Each run's log
rotates at 2 MiB with two retained segments; logs are capped at 90 files and
30 days on subsequent invocations. Successful live backups retain at most 30
files and 30 days. State files and directories are private to `deploy`.
Backups are the live pre-refresh database; `staged.sqlite3` is the candidate.
The job never restores a backup automatically and never overwrites the live DB.
Before fetching, `--base-snapshot data/catalog.json` applies the latest published
Git snapshot to staging. This preserves already-published observations if the
previous deployment failed or has not reached the live volume yet.

Every invocation also writes a sanitized status report in `state/reports/`.
New or changed source reports are copied there before temporary work is removed,
including reports for no-change and failed refreshes. Those small reports remain
available even when no Git commit was needed. Raw subprocess output is not logged
because network errors can contain credentials or response data; failure reports
identify the failed phase and exception type without copying those values.

After a push and explicit API trigger, verify the matching Coolify deployment and HTTPS health check;
the scheduler records publication success, not asynchronous deployment success.
If the deployed app fails, use Coolify rollback and investigate logs. Retain the
matching pre-refresh SQLite backup for operator-directed recovery if needed.
Do not replace a live SQLite file while application processes are running.

To pause scheduling, remove only this job's crontab line. A running refresh can
finish; later manual runs still use the same lock and checkpoint recovery.

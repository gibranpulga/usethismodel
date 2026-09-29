# UseThisModel

UseThisModel is a source-backed guide for choosing an AI model together with
the provider route, plan or offer, and harness that make it useful for a task.
It treats route pricing and capabilities as route-specific facts, MCP as a
harness capability, and benchmarks as separate objective measurements.

The route finder uses a source-backed SQLite catalog with a deterministic daily
maintenance pipeline. Discovery includes route-scoped offers, factual rankings,
deterministic quick-search facets, media-native pricing, price history, and local-only
pins/setup preferences.

## Stack

- Python 3.12 and Flask keep the web application small and self-contained.
- SQLite stores the catalog without a separate database service.
- SQL migration files and a `schema_migrations` table provide a minimal,
  explicit schema migration mechanism.
- Gunicorn serves the production app in a small Docker image suitable for
  Coolify.

## Local development

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # optional; export values in your shell if needed
flask --app wsgi run --debug --port 8000
```

Open <http://127.0.0.1:8000>. SQLite initializes automatically at
`instance/usethismodel.sqlite3` (or `DATABASE_PATH`). The health check is
<http://127.0.0.1:8000/health>.

For production-like website-only serving, run `gunicorn --bind 127.0.0.1:8000 wsgi:app`.

## Read-only MCP server

The same application exposes the catalogue as MCP at `/mcp`. It uses the existing
SQLite database and query/domain layer; it does not copy data or expose SQL. The
production endpoint is `https://usethismodel.codefiction.net/mcp` and its human
documentation is at `/mcp-info`.

Run the combined website and Streamable HTTP server locally:

```sh
uvicorn asgi:app --host 127.0.0.1 --port 8000
```

Or use local stdio transport:

```sh
python -m app.mcp_server
```

Remote client examples:

```yaml
# Hermes Agent: ~/.hermes/config.yaml
mcp_servers:
  usethismodel:
    url: "https://usethismodel.codefiction.net/mcp"
    trust: untrusted
```

```toml
# Codex CLI: ~/.codex/config.toml
[mcp_servers.usethismodel]
url = "https://usethismodel.codefiction.net/mcp"
```

```jsonc
// OpenCode v2: opencode.jsonc
{"mcp":{"servers":{"usethismodel":{"type":"remote","url":"https://usethismodel.codefiction.net/mcp","oauth":false}}}}
```

```json
// Pi: ~/.pi/agent/mcp.json or .pi/mcp.json
{"mcpServers":{"usethismodel":{"url":"https://usethismodel.codefiction.net/mcp","exposure":"direct"}}}
```

For stdio, replace each remote URL declaration with the client's local command
form invoking the repository environment's Python and `-m app.mcp_server`, with
the repository as its working directory.

All 16 tools are annotated read-only and return bounded, paginated results. They
include canonical model identity, exact provider route, prices, capabilities,
compatibility evidence, verification dates, and public sources where applicable.
Static MCP resources summarize models, providers, harnesses, active offers, and
benchmark metadata. `MCP_RATE_LIMIT_PER_MINUTE` controls per-client public HTTP
rate protection (default 60; enforced per worker). The transport accepts request
bodies up to 256 KiB. No tool schema or result includes application secrets,
provider keys, process environment, private Git credentials, or private agent
configuration.

## Verification

```sh
pip install -r requirements-dev.txt
ruff check .
pytest
docker build -t usethismodel:local .
make launch-audit
```

## Configuration

See [.env.example](.env.example). `FLASK_SECRET_KEY` should be a long random
value in deployed environments. `DATABASE_PATH` selects the SQLite file;
Coolify deployments should mount persistent storage at `/data` because the
container image stores the database at `/data/usethismodel.sqlite3`.

## Public read-only API and discovery

Human-readable API documentation is at `/api`; the versioned JSON root is
`/api/v1`. Resources cover models and individual canonical slugs, providers,
harnesses, offers, releases, benchmarks, compatibility, and route search.
Responses use a stable `{data, meta}` envelope and preserve null/`UNKNOWN`
instead of inferring missing facts. Combined filters include `tools=true`,
`max_output_price=1`, `harness=hermes-agent`, `mcp=true`, `offers=current`,
`releases=7-days`, and `type=3d`.

Crawler discovery is exposed through a grouped `/sitemap.xml`, `/robots.txt`,
Atom feeds for releases, price changes, current deals and expired deals, and a
combined JSON Feed at `/feeds/changes.json`. Arbitrary search and filter
combinations are canonicalized to their base page and marked `noindex,follow`;
stable entity pages remain indexable. Search crawlers are separated from model
training crawlers; see [the verified crawler policy](docs/crawler-policy.md).

Anonymous analytics use daily aggregate counters only. They cover searches
without query text, popular model and harness pages, filter-key combinations,
comparisons, deal clicks, API resources, and MCP request methods. No prompt,
search text, IP address, cookie, or visitor identifier is stored. The dashboard
under `/internal/analytics` requires `INTERNAL_DASHBOARD_TOKEN` and is not
publicly indexable.

## Project structure

```text
app/                 Flask app factory, SQLite access, templates and static UI
docs/                Product landscape and source research
migrations/          Ordered SQLite schema migrations
tests/               Application, route and SQLite initialization tests
Dockerfile           Production container definition
wsgi.py              WSGI entry point
requirements.txt     Runtime dependencies
```

## Product principles

- A model may have multiple provider routes with different prices and support.
- Open weights do not imply a free hosted API; a $0 price applies to a
  particular route or offer with terms and limits.
- Tool calling and MCP are distinct. Compatibility depends on the harness,
  provider access, route protocol support and model behavior.
- Benchmarks stay separate from recommendations, with source and method
  attached to measurements.
- Media generation prices keep their native units (image, second, audio minute,
  video, generation, or 3D generation) rather than being converted to tokens.
- Personal setup, pins, and saved comparisons stay in browser storage. API keys
  are never requested or stored.

See [the landscape research](docs/landscape-research.md) for the initial
competitor, data source and benchmark review.

## Coolify deployment

The repository is ready for Coolify's Dockerfile build pack. Configure a
service from the `main` branch, expose port `8000`, assign persistent storage
at `/data`, and set `FLASK_SECRET_KEY` as a production secret. Attach
`usethismodel.codefiction.net` to that service. The database must stay on the
`/data` volume so SQLite persists across container replacements.

Production is deployed at <https://usethismodel.codefiction.net>.
The container health probe is `python /app/healthcheck.py`; it checks `/health`
using Python's standard library. Gunicorn preloads the application so SQLite
migrations finish before the two workers fork.

The existing Coolify application UUID is `ild8duzk51xnfcuyxtyclzpg`. Its GitHub
source expects `gibranpulga/usethismodel.git` as the repository value and uses
the `main` branch. Persistent storage is mounted at `/data`, and
`FLASK_SECRET_KEY` is configured as a runtime-only environment variable.

For this workstation, the personal `coolify` skill manages the REST API over
SSH. Its credentials are stored outside this repository. Deployment was
verified on 2026-09-29: Docker build, healthy container, valid HTTPS, all
public routes, static assets, all SQLite migrations, and database
integrity passed. The catalog maintenance workflow is described below.


## Data maintenance

```sh
make data-update                  # fetch, reconcile, validate, export catalog and report
make data-dry-run                 # same analysis on a temporary database; no writes
make data-validate                # validate the selected SQLite database
make test
# Select a staging DB: make data-update DATABASE=/private/staged.sqlite3
```

The equivalent commands are `python -m app.data_update update [--dry-run]` and
`python -m app.data_update validate`, with `--database` and `--output-dir` options.
All legacy importer entry points now use the same safety pipeline.

Models.dev, OpenRouter and LiteLLM update public structured facts; official Hermes
documentation revisions are monitored via GitHub's structured API. No LLM or paid
API is needed. See [source semantics](docs/update-sources.md),
[maintenance policy](docs/data-maintenance.md), and [daily operations](docs/daily-data-update.md).

`data/catalog.json` is the reviewable deployment snapshot. Startup applies a new
snapshot once, in a validated SQLite transaction; an invalid snapshot rolls back.
The persistent database remains in the Coolify volume. Historical reports live in
`data/reports/` and private VPS `state/reports/`; unresolved evidence is in
`data/pending-review.json`. Do not hand-edit generated snapshots; update the source
observations and regenerate them.

### Migrations, backup, and restore

Migrations in `migrations/` run in numeric order at startup and are recorded in
`schema_migrations`; never edit an already-deployed migration. Add the next SQL
file and test both an empty database and a copy of production data.

For a consistent local backup with no application writer running:

```sh
sqlite3 instance/usethismodel.sqlite3 '.backup /private/usethismodel-backup.sqlite3'
```

Stop application writers before a manual restore, retain the displaced database,
copy the verified backup to `DATABASE_PATH`, then run `PRAGMA integrity_check`,
`PRAGMA foreign_key_check`, `make data-validate`, and a smoke test before restart.
The production scheduler makes online backups from the persistent `/data` volume;
full recovery details are in [daily operations](docs/daily-data-update.md).

### Manual updates and new catalog entities

Do not edit generated snapshot shards. Add or correct source observations through
an adapter in `app/update_sources.py`, run `make data-dry-run`, review the report,
then run `make data-update`. A provider must preserve exact route identifiers,
route-specific prices/limits/capabilities, and sources. A harness needs provider
compatibility modes, MCP facts, caveats, and sources. A benchmark needs a unique
name/version, stated metric, publisher evidence, and the harness/scaffold when one
was used. See [source adapter semantics](docs/update-sources.md).

### Logs, deployment, and common failures

Local Flask/Gunicorn logs go to the terminal. The VPS updater keeps private,
rotated logs and sanitized reports under `~/usethismodel-updater/state/`; Coolify
holds build/runtime logs. Source collapse, total source outage, invalid data,
dirty/diverged Git state, failed tests, or snapshot validation stop publication
without erasing the last valid catalog. For deployment and cron recovery, follow
[daily operations](docs/daily-data-update.md).

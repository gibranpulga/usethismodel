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

For production-like local serving, run `gunicorn --bind 127.0.0.1:8000 wsgi:app`.

## Verification

```sh
pip install -r requirements-dev.txt
ruff check .
pytest
docker build -t usethismodel:local .
```

## Configuration

See [.env.example](.env.example). `FLASK_SECRET_KEY` should be a long random
value in deployed environments. `DATABASE_PATH` selects the SQLite file;
Coolify deployments should mount persistent storage at `/data` because the
container image stores the database at `/data/usethismodel.sqlite3`.

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
placeholder routes, static assets, both SQLite migrations, and database
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

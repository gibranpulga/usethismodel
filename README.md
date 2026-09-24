# UseThisModel

UseThisModel is a source-backed guide for choosing an AI model together with
the provider route, plan or offer, and harness that make it useful for a task.
It treats route pricing and capabilities as route-specific facts, MCP as a
harness capability, and benchmarks as separate objective measurements.

This repository is the application foundation. The catalog, recommendations,
data imports and offer tracking are later stages.

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

See [the landscape research](docs/landscape-research.md) for the initial
competitor, data source and benchmark review.

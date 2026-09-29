import re
import sqlite3
from pathlib import Path

from flask import current_app, g

MIGRATION_NAME = re.compile(r"^(?P<version>\d+)_.+\.sql$")


def get_db():
    if "db" not in g:
        Path(current_app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        db = get_db()
        db.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        applied = {row[0] for row in db.execute("SELECT version FROM schema_migrations")}
        migrations_dir = Path(__file__).resolve().parent.parent / "migrations"
        migrations = []
        for path in migrations_dir.glob("*.sql"):
            match = MIGRATION_NAME.match(path.name)
            if match:
                migrations.append((int(match.group("version")), path))

        for version, migration in sorted(migrations):
            if version in applied:
                continue
            db.executescript(migration.read_text(encoding="utf-8"))
            db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
        db.commit()

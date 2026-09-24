import sqlite3
from pathlib import Path
from flask import current_app, g


def get_db():
    if "db" not in g:
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
        db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        applied = {row[0] for row in db.execute("SELECT version FROM schema_migrations")}
        if 1 not in applied:
            migration = Path(__file__).resolve().parent.parent / "migrations" / "001_initial.sql"
            db.executescript(migration.read_text(encoding="utf-8"))
            db.execute("INSERT INTO schema_migrations(version) VALUES (1)")
        db.commit()

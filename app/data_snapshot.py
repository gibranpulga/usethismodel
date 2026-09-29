"""Versioned public catalog snapshots, applied transactionally on deployment."""
import hashlib
import json
from pathlib import Path

EXCLUDED = {'schema_migrations', 'applied_snapshots'}


def tables(db):
    return [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name") if r[0] not in EXCLUDED]


def snapshot(db):
    return {'version': 1, 'tables': {t: [dict(r) for r in db.execute(f'SELECT * FROM "{t}" ORDER BY rowid')] for t in tables(db)}}


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def snapshot_text(db):
    data = snapshot(db)
    parts = ['{"version":1,"tables":{']
    for index, (table, rows) in enumerate(data['tables'].items()):
        if index:
            parts[-1] += ','
        parts.append(encode(table) + ':[')
        parts.extend(encode(row) + (',' if i < len(rows) - 1 else '') for i, row in enumerate(rows))
        parts.append(']')
    parts.append('}}')
    return '\n'.join(parts) + '\n'


def apply_snapshot(db, path):
    path = Path(path)
    if not path.exists():
        return
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if db.execute('SELECT 1 FROM applied_snapshots WHERE digest=?', (digest,)).fetchone():
        return
    data = json.loads(raw)
    if data.get('version') != 1 or set(data['tables']) != set(tables(db)):
        raise ValueError('Catalog snapshot schema mismatch')
    db.execute('BEGIN')
    try:
        db.execute('PRAGMA defer_foreign_keys=ON')
        for table in tables(db):
            db.execute(f'DELETE FROM "{table}"')
        for table, rows in data['tables'].items():
            allowed = {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
            for row in rows:
                if not set(row) <= allowed:
                    raise ValueError('Unknown snapshot column')
                columns = ','.join(f'"{c}"' for c in row)
                db.execute(f'INSERT INTO "{table}" ({columns}) VALUES ({",".join("?" for _ in row)})', list(row.values()))
        from .data_update import validate
        validate(db)
        db.execute('INSERT INTO applied_snapshots(digest) VALUES(?)', (digest,))
        db.commit()
    except Exception:
        db.rollback()
        raise

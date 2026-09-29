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


def snapshot_text(db, output_dir=None):
    if output_dir is None:
        return encode(snapshot(db)) + '\n'
    # Bound individual Git files as observation history grows. Shards are stable
    # by row order; a new observation usually changes only the final shard.
    root = Path(output_dir)
    manifest = {'version': 2, 'tables': {}}
    expected = set()
    for table in tables(db):
        cursor = db.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
        chunks = []
        index = 0
        while rows := cursor.fetchmany(1000):
            content = '[\n' + ',\n'.join(encode(dict(row)) for row in rows) + '\n]\n'
            relative = f'snapshot/{table}/{index:06d}.json'
            path = root / relative
            expected.add(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists() or path.read_text() != content:
                temporary = path.with_suffix('.tmp')
                temporary.write_text(content)
                temporary.replace(path)
            chunks.append({'path': relative, 'sha256': hashlib.sha256(content.encode()).hexdigest()})
            index += 1
        manifest['tables'][table] = chunks
    for path in (root / 'snapshot').glob('*/*.json'):
        if path not in expected:
            path.unlink()
    return json.dumps(manifest, indent=2, sort_keys=True) + '\n'


def apply_snapshot(db, path):
    path = Path(path)
    if not path.exists():
        return
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if db.execute('SELECT 1 FROM applied_snapshots WHERE digest=?', (digest,)).fetchone():
        return
    data = json.loads(raw)
    if data.get('version') == 2:
        loaded = {}
        for table, chunks in data['tables'].items():
            loaded[table] = []
            for chunk in chunks:
                shard = (path.parent / chunk['path']).resolve()
                if not shard.is_relative_to(path.parent.resolve()):
                    raise ValueError('Snapshot shard escapes catalog directory')
                content = shard.read_bytes()
                if hashlib.sha256(content).hexdigest() != chunk['sha256']:
                    raise ValueError('Snapshot shard checksum mismatch')
                loaded[table].extend(json.loads(content))
        data = {'version': 1, 'tables': loaded}
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

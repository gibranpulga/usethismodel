"""Versioned public catalog snapshots, applied transactionally on deployment."""
import hashlib
import json
from pathlib import Path

# Operational state is intentionally outside the published catalog snapshot.
# Snapshot application must never erase local usage counters.
EXCLUDED = {'schema_migrations', 'applied_snapshots', 'analytics_daily', 'rate_limit_windows'}
OPTIONAL_SNAPSHOT_TABLES = {'documentation_monitor_state', 'plan_value_history'}


def tables(db):
    return [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name") if r[0] not in EXCLUDED]


def dependency_order(db):
    """Parents first for insertion, children first for deletion (avoids FK scans)."""
    names = tables(db)
    ordered, visiting = [], set()

    def visit(table):
        if table in ordered:
            return
        if table in visiting:
            raise ValueError('Cyclic snapshot foreign keys')
        visiting.add(table)
        parents = {row[2] for row in db.execute(f'PRAGMA foreign_key_list("{table}")')}
        for parent in sorted(parents & set(names)):
            visit(parent)
        visiting.remove(table)
        ordered.append(table)

    for table in names:
        visit(table)
    return ordered


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
    expected = set(tables(db))
    supplied = set(data.get('tables', {}))
    if (data.get('version') != 1 or not supplied <= expected
            or expected - supplied - OPTIONAL_SNAPSHOT_TABLES):
        raise ValueError('Catalog snapshot schema mismatch')
    for table in expected - supplied:
        data['tables'][table] = []
    db.execute('BEGIN')
    try:
        db.execute('PRAGMA defer_foreign_keys=ON')
        order = dependency_order(db)
        for table in reversed(order):
            db.execute(f'DELETE FROM "{table}"')
        for table in order:
            rows = data['tables'][table]
            allowed = {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
            for row in rows:
                if not set(row) <= allowed:
                    raise ValueError('Unknown snapshot column')
                columns = ','.join(f'"{c}"' for c in row)
                db.execute(f'INSERT INTO "{table}" ({columns}) VALUES ({",".join("?" for _ in row)})', list(row.values()))
        if 'access_semantics' in {r[1] for r in db.execute('PRAGMA table_info(provider_offerings)')}:
            db.execute("""UPDATE provider_offerings SET
              access_semantics=CASE
                WHEN free_status='FREE' AND EXISTS (SELECT 1 FROM providers p WHERE p.id=provider_offerings.provider_id AND (lower(p.name) LIKE '%token plan%' OR lower(p.name) LIKE '%coding plan%' OR lower(p.name) LIKE '%gitlab duo%' OR lower(p.name) LIKE '%opencode go%')) THEN 'INCLUDED_WITH_SUBSCRIPTION'
                WHEN free_status='FREE' THEN 'FREE_API'
                WHEN free_status='PAID' THEN 'PAID_API' ELSE 'UNKNOWN' END,
              access_requirement=CASE WHEN EXISTS (SELECT 1 FROM providers p WHERE p.id=provider_offerings.provider_id AND (lower(p.name) LIKE '%token plan%' OR lower(p.name) LIKE '%coding plan%' OR lower(p.name) LIKE '%gitlab duo%' OR lower(p.name) LIKE '%opencode go%')) THEN (SELECT p.name FROM providers p WHERE p.id=provider_offerings.provider_id) ELSE NULL END""")
            db.execute("UPDATE provider_offerings SET free_status='PAID' WHERE access_semantics='INCLUDED_WITH_SUBSCRIPTION' AND free_status='FREE'")
        from .data_update import validate
        validate(db)
        db.execute('INSERT INTO applied_snapshots(digest) VALUES(?)', (digest,))
        db.commit()
    except Exception:
        db.rollback()
        raise

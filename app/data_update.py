"""Deterministic observations, precedence, safety gates and reviewable catalog updates."""
import argparse
import hashlib
import json
import math
import os
import sqlite3
import tempfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from .catalog import _model, _provider, _source
from .data_snapshot import encode, snapshot_text

PRICES = {'input_price': 'INPUT', 'output_price': 'OUTPUT', 'cache_read_price': 'CACHE_READ', 'cache_write_price': 'CACHE_WRITE'}
COLUMNS = {'context_window': 'context_limit', 'max_output_tokens': 'max_output_tokens', 'tool_calling': 'tool_support', 'structured_output': 'structured_output_support'}
CATEGORIES = ['New models', 'New provider offerings', 'Price increases', 'Price reductions', 'New free routes', 'Expired free routes', 'New offers', 'Expired offers', 'Harness changes', 'Source failures', 'Conflicts', 'Manual-review items']


def priority(source, field):
    """Priority is assigned here, never trusted from an incoming payload."""
    if field.startswith('benchmark:'):
        return 10 if source == 'benchmark_publisher' else 100
    return {'official_announcement': 5, 'official_provider': 10, 'official_docs': 10, 'official_metadata': 15, 'openrouter': 20, 'models.dev': 30, 'litellm': 40, 'legacy-unverified': 90}.get(source, 60)


def valid_value(field, value):
    if value is None:
        return False
    if field in PRICES:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1_000_000
    if field in ('context_window', 'max_output_tokens'):
        return isinstance(value, int) and not isinstance(value, bool) and 0 < value <= 100_000_000
    if field in ('tool_calling', 'structured_output', 'open_weights', 'vision', 'reasoning'):
        return isinstance(value, bool)
    if field == 'release_date':
        try:
            parsed = date.fromisoformat(value + '-01' if isinstance(value, str) and len(value) == 7 else value)
            return date(2000, 1, 1) <= parsed <= date.today()
        except (TypeError, ValueError):
            return False
    return False


def review(db, report, now, entity, field, current, proposed, sources, reason, evidence='', confidence='LOW'):
    values = (entity, field, encode(current), encode(proposed), encode(sources), reason)
    key = hashlib.sha256(encode((entity, field, encode(proposed), encode(sources), reason)).encode()).hexdigest()[:24]
    if not db.execute('SELECT 1 FROM review_queue WHERE id=?', (key,)).fetchone():
        db.execute('INSERT INTO review_queue(id,entity,proposed_change,current_value,proposed_value,sources,evidence,confidence,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)', (key, *values[:5], evidence or reason, confidence, reason, now))
        report['Manual-review items'].append({'id': key, 'entity': entity, 'field': field, 'reason': reason})
    return key


def observe(db, entity, field, source, url, source_id, value, now, accepted=True, evidence='Structured source field'):
    raw = encode(value)
    last = db.execute('SELECT * FROM data_observations WHERE entity=? AND field=? AND source=? AND accepted=? ORDER BY id DESC LIMIT 1', (entity, field, source, int(accepted))).fetchone()
    if not accepted:
        known = db.execute('SELECT id FROM data_observations WHERE entity=? AND field=? AND source=? AND value_json=? AND accepted=0', (entity, field, source, raw)).fetchone()
        if known:
            return known[0]
    if last and json.loads(last['value_json']) == value and last['accepted'] == int(accepted):
        return last['id']
    return db.execute('INSERT INTO data_observations(entity,field,source,source_url,source_id,value_json,priority,observed_at,accepted,evidence) VALUES(?,?,?,?,?,?,?,?,?,?)', (entity, field, source, url, source_id, raw, priority(source, field), now, int(accepted), evidence)).lastrowid


def quarantine_legacy(db, report, now):
    for row in db.execute('SELECT pr.*,s.url,s.source_type FROM pricing_records pr LEFT JOIN sources s ON s.id=pr.source_id').fetchall():
        if valid_value('input_price', row['amount']):
            continue
        entity = f"offering:{row['offering_id']}"
        field = next((k for k, value in PRICES.items() if value == row['price_type']), row['price_type'])
        observe(db, entity, field, source_for_url(row['url'], row['source_type']), row['url'] or '', row['source_id'], row['amount'], now, False, 'Quarantined legacy pricing row: ' + encode(dict(row)))
        review(db, report, now, entity, field, row['amount'], None, [row['url']], 'Legacy invalid price quarantined; original row preserved as evidence', encode(dict(row)))
        db.execute('DELETE FROM pricing_records WHERE id=?', (row['id'],))
        if row['valid_until'] is None and not db.execute('SELECT 1 FROM pricing_records WHERE offering_id=? AND price_type=? AND valid_until IS NULL', (row['offering_id'], row['price_type'])).fetchone():
            previous = db.execute('SELECT id,amount FROM pricing_records WHERE offering_id=? AND price_type=? AND amount>=0 ORDER BY id DESC LIMIT 1', (row['offering_id'], row['price_type'])).fetchone()
            if previous and valid_value('input_price', previous['amount']):
                db.execute('UPDATE pricing_records SET valid_until=NULL WHERE id=?', (previous['id'],))
    for row in db.execute('SELECT o.*,s.url,s.source_type FROM provider_offerings o LEFT JOIN sources s ON s.id=o.source_id').fetchall():
        for field, column in COLUMNS.items():
            if field not in ('context_window', 'max_output_tokens') or row[column] is None or valid_value(field, row[column]):
                continue
            entity = f"offering:{row['id']}"
            observe(db, entity, field, source_for_url(row['url'], row['source_type']), row['url'] or '', row['source_id'], row[column], now, False, 'Invalid legacy limit retained as evidence')
            review(db, report, now, entity, field, row[column], None, [row['url']], 'Legacy invalid token limit quarantined')
            db.execute(f'UPDATE provider_offerings SET {column}=NULL WHERE id=?', (row['id'],))


def seed_observations(db, now, report):
    if db.execute('SELECT 1 FROM data_observations WHERE accepted=1 LIMIT 1').fetchone():
        return
    for row in db.execute('SELECT pr.*,s.url,s.source_type FROM pricing_records pr LEFT JOIN sources s ON s.id=pr.source_id WHERE valid_until IS NULL ORDER BY pr.id').fetchall():
        field = next((k for k, v in PRICES.items() if v == row['price_type']), None)
        if field:
            source = source_for_url(row['url'], row['source_type'])
            observe(db, f"offering:{row['offering_id']}", field, source, row['url'] or '', row['source_id'], row['amount'], now, evidence='Existing catalog price; original row retained')
    for row in db.execute('SELECT o.*,s.url,s.source_type FROM provider_offerings o LEFT JOIN sources s ON s.id=o.source_id').fetchall():
        for field, column in COLUMNS.items():
            value = row[column]
            if value in ('YES', 'NO'):
                value = value == 'YES'
            if valid_value(field, value):
                observe(db, f"offering:{row['id']}", field, source_for_url(row['url'], row['source_type']), row['url'] or '', row['source_id'], value, now, evidence='Existing catalog metadata')
    for row in db.execute('SELECT c.*,s.url,s.source_type FROM offering_capabilities c LEFT JOIN sources s ON s.id=c.source_id').fetchall():
        if row['capability'] in ('vision', 'reasoning') and row['state'] in ('YES', 'NO'):
            observe(db, f"offering:{row['offering_id']}", row['capability'], source_for_url(row['url'], row['source_type']), row['url'] or '', row['source_id'], row['state'] == 'YES', now, evidence='Existing route capability with original provenance')
    # Seed dates and benchmark scores have no per-value supporting evidence. Preserve,
    # explicitly flag, and do not elevate a publisher homepage to verified evidence.
    for row in db.execute('SELECT id,released_at FROM models WHERE released_at IS NOT NULL').fetchall():
        observe(db, f"model:{row['id']}", 'release_date', 'legacy-unverified', '', None, row['released_at'], now)
        review(db, report, now, f"model:{row['id']}", 'release_date', row['released_at'], None, [], 'Legacy release date has no announcement or per-value evidence')
    for row in db.execute('SELECT br.*,s.url FROM benchmark_results br LEFT JOIN sources s ON s.id=br.source_id').fetchall():
        review(db, report, now, f"benchmark_result:{row['id']}", 'score', row['score'], None, [row['url']], 'Legacy benchmark score needs publisher result evidence, version and harness verification')


def source_for_url(url, source_type=None):
    if source_type in {"official_provider", "official_docs", "official_metadata", "official_announcement", "benchmark_publisher"}:
        return source_type
    if url and 'models.dev/' in url:
        return 'models.dev'
    if url and 'openrouter.ai/api/' in url:
        return 'openrouter'
    if url and 'litellm' in url:
        return 'litellm'
    return 'legacy-unverified'


def validate(db):
    errors = []
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        errors.append('SQLite integrity check failed')
    if db.execute('PRAGMA foreign_key_check').fetchone():
        errors.append('Foreign key violation')
    for row in db.execute('SELECT id,amount FROM pricing_records'):
        if not valid_value('input_price', row['amount']):
            errors.append(f"Invalid price record {row['id']}")
    for row in db.execute('SELECT id,context_limit,max_output_tokens FROM provider_offerings'):
        for key in ('context_limit', 'max_output_tokens'):
            if row[key] is not None and not valid_value('context_window', row[key]):
                errors.append(f"Invalid limit on offering {row['id']}")
    if db.execute("SELECT 1 FROM provider_offerings o WHERE free_status='FREE' AND (NOT EXISTS(SELECT 1 FROM pricing_records p WHERE p.offering_id=o.id AND p.price_type='INPUT' AND p.amount=0 AND p.valid_until IS NULL) OR NOT EXISTS(SELECT 1 FROM pricing_records p WHERE p.offering_id=o.id AND p.price_type='OUTPUT' AND p.amount=0 AND p.valid_until IS NULL))").fetchone():
        errors.append('Free route without both explicit zero prices')
    if db.execute("SELECT 1 FROM models WHERE release_date_kind='first_seen'").fetchone():
        errors.append('Discovery date used as release date')
    if errors:
        raise ValueError('; '.join(errors[:20]))
    return {'integrity': 'ok', 'foreign_keys': 'ok', 'prices': 'ok', 'limits': 'ok', 'free_routes': 'ok', 'release_dates': 'ok'}


def guard_sources(db, records, manifests, report, now):
    grouped = defaultdict(list)
    for record in records:
        grouped[record['source']].append(record)
    allowed = []
    for source, items in sorted(grouped.items()):
        prior = db.execute('SELECT manifest_json FROM source_state WHERE source=?', (source,)).fetchone()
        old = json.loads(prior[0]) if prior else {}
        priced = sum('input_price' in r['fields'] and 'output_price' in r['fields'] for r in items)
        reasons = []
        if old.get('count', 0) >= 10 and len(items) < old['count'] * .75:
            reasons.append('Catalog collapsed by more than 25%')
        if old.get('priced', 0) >= 10 and priced < old['priced'] * .75:
            reasons.append('Priced routes disappeared by more than 25%')
        providers = defaultdict(list)
        for item in items:
            providers[item['provider_key']].append(item)
        for missing in sorted(set(old.get('providers', {})) - set(providers)):
            if old['providers'][missing].get('count', 0) >= 10:
                reasons.append(f'{missing}: entire provider disappeared')
        for provider, routes in providers.items():
            old_routes = old.get('providers', {}).get(provider, {})
            zeros = sum(r['fields'].get('input_price') == 0 and r['fields'].get('output_price') == 0 for r in routes)
            priced_routes = sum('input_price' in r['fields'] and 'output_price' in r['fields'] for r in routes)
            if priced_routes >= 3 and zeros / priced_routes >= .95 and old_routes.get('paid', 0) >= 3 and (priced_routes - zeros) < old_routes['paid'] * .25:
                reasons.append(f'{provider}: formerly paid provider now almost entirely zero')
            if old_routes.get('count', 0) >= 10 and len(routes) < old_routes['count'] * .75:
                reasons.append(f'{provider}: route count collapsed by more than 25%')
        if reasons:
            report['Source failures'].append({'source': source, 'error': '; '.join(reasons), 'action': 'Quarantined; previous data retained'})
            review(db, report, now, source, 'catalog', old, manifests.get(source), [items[0]['source_url']], '; '.join(reasons))
            # Keep conflicting/suspicious factual evidence even when a whole fetch is quarantined.
            for r in items:
                for field, value in sorted(r['fields'].items()):
                    observe(db, f"source-route:{r['provider_key']}:{r['api_model_id']}", field, source, r['source_url'], None, value, now, False, '; '.join(reasons))
            continue
        listings = sorted(f"{r['provider_key']}:{r['api_model_id']}" for r in items)
        for missing in sorted(set(old.get('listings', [])) - set(listings)):
            entity = 'source-route:' + missing
            reason = 'Route missing from successful source; expiry unconfirmed, previous facts retained'
            observe(db, entity, 'listed', source, items[0]['source_url'], None, False, now, False, reason)
            review(db, report, now, entity, 'listing removed', True, False, [items[0]['source_url']], reason)
        manifest = dict(manifests.get(source, {}))
        manifest['listings'] = listings
        manifest.update(count=len(items), priced=priced, providers={p: {'count': len(rs), 'paid': sum((r['fields'].get('input_price') or 0) > 0 or (r['fields'].get('output_price') or 0) > 0 for r in rs)} for p, rs in sorted(providers.items())})
        db.execute('INSERT INTO source_state VALUES(?,?) ON CONFLICT(source) DO UPDATE SET manifest_json=excluded.manifest_json', (source, encode(manifest)))
        allowed.extend(items)
    return allowed


def resolve(db, entity, field, report, now):
    candidates = db.execute('''SELECT d.* FROM data_observations d JOIN
        (SELECT source,MAX(id) id FROM data_observations WHERE entity=? AND field=? AND accepted=1 GROUP BY source) latest ON latest.id=d.id
        ORDER BY d.priority,d.source''', (entity, field)).fetchall()
    if not candidates:
        return
    chosen = candidates[0]
    for other in candidates[1:]:
        if json.loads(other['value_json']) != json.loads(chosen['value_json']):
            key = review(db, report, now, entity, field, json.loads(chosen['value_json']), json.loads(other['value_json']), [chosen['source_url'], other['source_url']], 'Sources disagree; displayed value follows precedence', f"Selected {chosen['source']} ({chosen['priority']}); alternative {other['source']} ({other['priority']})", 'MEDIUM')
            if any(r['id'] == key for r in report['Manual-review items']):
                report['Conflicts'].append({'entity': entity, 'field': field, 'selected': json.loads(chosen['value_json']), 'alternative': json.loads(other['value_json']), 'sources': [chosen['source_url'], other['source_url']]})
    previous = db.execute('SELECT observation_id FROM selected_facts WHERE entity=? AND field=?', (entity, field)).fetchone()
    if previous and previous[0] == chosen['id']:
        return
    value = json.loads(chosen['value_json'])
    kind, ident = entity.split(':')
    ident = int(ident)
    if kind == 'offering':
        if field in PRICES:
            old = db.execute('SELECT amount,source_id FROM pricing_records WHERE offering_id=? AND price_type=? AND valid_until IS NULL ORDER BY id DESC LIMIT 1', (ident, PRICES[field])).fetchone()
            if not old or old['amount'] != value or old['source_id'] != chosen['source_id']:
                db.execute('UPDATE pricing_records SET valid_until=? WHERE offering_id=? AND price_type=? AND valid_until IS NULL', (now, ident, PRICES[field]))
                db.execute('INSERT INTO pricing_records(offering_id,price_type,amount,source_id,valid_from,fetched_at) VALUES(?,?,?,?,?,?)', (ident, PRICES[field], value, chosen['source_id'], now, now))
                if old and old['amount'] != value:
                    report['Price increases' if value > old['amount'] else 'Price reductions'].append({'entity': entity, 'field': field, 'before': old['amount'], 'after': value, 'source': chosen['source_url']})
        elif field in COLUMNS:
            stored = ('YES' if value else 'NO') if isinstance(value, bool) else value
            db.execute(f'UPDATE provider_offerings SET {COLUMNS[field]}=?,fetched_at=? WHERE id=?', (stored, now, ident))
        elif field in ('vision', 'reasoning'):
            db.execute('INSERT INTO offering_capabilities(offering_id,capability,state,source_id) VALUES(?,?,?,?) ON CONFLICT(offering_id,capability) DO UPDATE SET state=excluded.state,source_id=excluded.source_id', (ident, field, 'YES' if value else 'NO', chosen['source_id']))
    elif field == 'release_date':
        provenance = 'official' if chosen['priority'] <= 15 else 'aggregator' if chosen['priority'] < 90 else 'unverified'
        db.execute('UPDATE models SET released_at=?,release_date_kind=? WHERE id=?', (value, provenance, ident))
    elif field == 'open_weights':
        db.execute('UPDATE models SET open_weights=? WHERE id=?', (int(value), ident))
    db.execute('INSERT INTO selected_facts VALUES(?,?,?) ON CONFLICT(entity,field) DO UPDATE SET observation_id=excluded.observation_id', (entity, field, chosen['id']))


def update(db, records, failures, manifests, now=None):
    now = now or datetime.now(timezone.utc).isoformat(timespec='seconds')
    report = {category: [] for category in CATEGORIES}
    report['Source failures'].extend(failures)
    quarantine_legacy(db, report, now)
    seed_observations(db, now, report)
    records = guard_sources(db, records, manifests, report, now)
    if not records:
        raise ValueError('No source passed safety checks; production data unchanged')
    touched = set()
    provider_ids = {}
    proposals = defaultdict(list)
    for record in sorted(records, key=lambda r: (r['source'], r['provider_key'], r['api_model_id'])):
        source = record['source']
        sid = _source(db, source, record['source_url'])
        provider_key = record['provider_key']
        if provider_key not in provider_ids:
            # Preserve existing display identities; models.dev names otherwise authoritative for naming.
            aliases = {'zai': 'Z.ai', 'z-ai': 'Z.ai', 'google': 'Google AI', 'moonshotai': 'Moonshot AI', 'deepinfra': 'DeepInfra'}
            name = aliases.get(provider_key, record['provider_name'])
            found = db.execute('SELECT id FROM providers WHERE lower(name)=lower(?)', (name,)).fetchone()
            provider_ids[provider_key] = found[0] if found else _provider(db, name)
        pid = provider_ids[provider_key]
        existing = db.execute('SELECT id,model_id FROM provider_offerings WHERE provider_id=? AND api_model_id=?', (pid, record['api_model_id'])).fetchone()
        if existing:
            oid, mid = existing['id'], existing['model_id']
        else:
            # Exact provider aliases are stronger than inferred canonical names.
            alias = db.execute('SELECT model_id FROM model_aliases WHERE provider_id=? AND alias=?', (pid, record['api_model_id'])).fetchone()
            before = db.execute('SELECT count(*) FROM models').fetchone()[0]
            mid = alias[0] if alias else _model(db, record['canonical_slug'], record['name'], record['canonical_slug'], False, 'text', sid)
            if db.execute('SELECT count(*) FROM models').fetchone()[0] > before:
                db.execute('UPDATE models SET first_seen_at=? WHERE id=?', (now, mid))
                report['New models'].append({'id': mid, 'name': record['name'], 'slug': record['canonical_slug'], 'first_seen_at': now})
                # Names shared by multiple canonical identities require human/optional Hermes interpretation.
                duplicates = db.execute('SELECT canonical_slug FROM models WHERE id!=? AND lower(canonical_name)=lower(?)', (mid, record['name'])).fetchall()
                if duplicates:
                    review(db, report, now, f'model:{mid}', 'canonical identity', record['canonical_slug'], [r[0] for r in duplicates], [record['source_url']], 'Similar name has a different canonical ID; no automatic fuzzy merge')
            oid = db.execute('INSERT INTO provider_offerings(model_id,provider_id,api_model_id,source_id,fetched_at,first_seen_at) VALUES(?,?,?,?,?,?)', (mid, pid, record['api_model_id'], sid, now, now)).lastrowid
            db.execute('INSERT OR IGNORE INTO model_aliases(model_id,alias,provider_id,source_id) VALUES(?,?,?,?)', (mid, record['api_model_id'], pid, sid))
            report['New provider offerings'].append({'id': oid, 'provider': record['provider_name'], 'model': record['api_model_id']})
        for field, values in sorted(record.get('rejected_fields', {}).items()):
            entity = f'offering:{oid}'
            for value in values:
                observe(db, entity, field, source, record['source_url'], sid, value, now, False, 'Ambiguous source aliases disagree')
            review(db, report, now, entity, field, None, values, [record['source_url']], 'Conflicting values within one source; retained previous value')
        for field, value in sorted(record['fields'].items()):
            if value is None:
                continue
            entity = f'model:{mid}' if field in ('release_date', 'open_weights') else f'offering:{oid}'
            proposals[(entity, field, source)].append((value, record['source_url'], sid))
    for (entity, field, source), entries in sorted(proposals.items()):
        distinct = {encode(value) for value, _, _ in entries}
        ambiguous = len(distinct) > 1
        old = db.execute('SELECT d.value_json FROM selected_facts s JOIN data_observations d ON d.id=s.observation_id WHERE s.entity=? AND s.field=?', (entity, field)).fetchone()
        current = json.loads(old[0]) if old else None
        for value, url, sid in entries:
            accepted = valid_value(field, value) and not ambiguous
            reason = 'Conflicting values within one source; retained previous value' if ambiguous else 'Invalid or unsupported structured value quarantined'
            if accepted and field in PRICES and current and value > current * 10:
                accepted = False
                reason = 'Price increased by more than 10x without an explanation; manual review required'
            observe(db, entity, field, source, url, sid, value, now, accepted, reason if not accepted else 'Structured source field')
            if not accepted:
                review(db, report, now, entity, field, current, value, [url], reason)
            else:
                touched.add((entity, field))
    # Include bootstrap observations so retained facts also have an explicit selection.
    touched.update((r[0], r[1]) for r in db.execute("SELECT DISTINCT entity,field FROM data_observations WHERE accepted=1 AND (entity LIKE 'model:%' OR entity LIKE 'offering:%')"))
    for entity, field in sorted(touched):
        resolve(db, entity, field, report, now)
    for row in db.execute('SELECT id,free_status FROM provider_offerings').fetchall():
        prices = dict(db.execute("SELECT price_type,amount FROM pricing_records WHERE offering_id=? AND valid_until IS NULL AND price_type IN ('INPUT','OUTPUT') ORDER BY id", (row['id'],)).fetchall())
        status = 'FREE' if prices.get('INPUT') == 0 and prices.get('OUTPUT') == 0 else 'PAID' if any(v > 0 for v in prices.values()) else 'UNKNOWN'
        if row['free_status'] != status:
            db.execute('UPDATE provider_offerings SET free_status=? WHERE id=?', (status, row['id']))
            if status == 'FREE':
                report['New free routes'].append({'offering': row['id']})
            elif row['free_status'] == 'FREE':
                report['Expired free routes'].append({'offering': row['id']})
    for offer in db.execute("SELECT id,title FROM offers WHERE status='ACTIVE' AND ends_at IS NOT NULL AND ends_at<?", (now[:10],)).fetchall():
        db.execute("UPDATE offers SET status='EXPIRED' WHERE id=?", (offer['id'],))
        report['Expired offers'].append(dict(offer))
    report['validation'] = validate(db)
    report['records_changed'] = {key: len(report[key]) for key in CATEGORIES}
    return report


def monitor_harnesses(db, records, failures, manifests, report, now):
    report['Source failures'].extend(failures)
    for record in records:
        source = record['source']
        prior = db.execute('SELECT manifest_json FROM source_state WHERE source=?', (source,)).fetchone()
        previous = json.loads(prior[0]) if prior else None
        current = {'content_hash': record['content_hash'], 'url': record['url'], 'evidence': record['evidence']}
        if previous and previous.get('content_hash') != current['content_hash']:
            report['Harness changes'].append({'name': record['name'], 'before': previous['content_hash'], 'after': current['content_hash'], 'source': record['url']})
            review(db, report, now, record['name'], 'documentation changed', previous, current, [record['source_url'], record['url']], 'Official documentation changed; capability interpretation requires review', encode(record['evidence']), 'HIGH')
        db.execute('INSERT INTO source_state VALUES(?,?) ON CONFLICT(source) DO UPDATE SET manifest_json=excluded.manifest_json', (source, encode(current)))
    report['records_changed'] = {key: len(report[key]) for key in CATEGORIES}


def write_outputs(db, report, output_dir, now):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    body = snapshot_text(db, output)
    digest = hashlib.sha256(body.encode()).hexdigest()
    catalog = output / 'catalog.json'
    changed = not catalog.exists() or catalog.read_text() != body
    if changed:
        atomic_write(catalog, body)
    queue = [dict(r) for r in db.execute("SELECT * FROM review_queue WHERE status='PENDING' ORDER BY id")]
    atomic_write(output / 'pending-review.json', json.dumps(queue, indent=2, ensure_ascii=False) + '\n')
    meaningful = any(report[c] for c in CATEGORIES)
    # One stable no-change report per day; repeated identical runs never create empty commits.
    report_key = hashlib.sha256(encode(report).encode()).hexdigest()[:12]
    path = output / 'reports' / f'{now[:10]}-{report_key}.md'
    if not path.exists():
        lines = [f'# UseThisModel daily data report — {now[:10]}', '', f'Catalog digest: `{digest}`', '', f'Data snapshot changed: {changed}. Validation: passed.', '', ' | '.join(f'{category}: {len(report[category])}' for category in CATEGORIES), '']
        for category in CATEGORIES:
            lines += [f'## {category}', '']
            entries = report[category]
            for entry in entries:
                ident = entry.get('offering') or (entry.get('entity', '').split(':')[1] if entry.get('entity', '').startswith('offering:') else None)
                label = db.execute('SELECT p.name,o.api_model_id FROM provider_offerings o JOIN providers p ON p.id=o.provider_id WHERE o.id=?', (ident,)).fetchone() if ident else None
                lines.append('- ' + (f'**{label[0]} / {label[1]}**: ' if label else '') + encode(entry))
            if not entries:
                lines.append('None.')
            lines.append('')
        lines += ['## Review policy', '', 'Pending items are evidence for human or optional Hermes review. No LLM was required or invoked. Legacy dates remain unverified; first_seen_at is never an official release date.', '']
        atomic_write(path, '\n'.join(lines))
    return {'snapshot_changed': changed, 'meaningful_changes': meaningful, 'report': str(path), 'pending_reviews': len(queue), **report['records_changed']}


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(content)
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['update', 'validate'])
    parser.add_argument('--database', default=os.environ.get('DATABASE_PATH', 'instance/usethismodel.sqlite3'))
    parser.add_argument('--output-dir', default='data')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--base-snapshot', help='Reconcile this published snapshot into staging before fetching')
    args = parser.parse_args()
    from . import create_app
    from .db import get_db
    from .update_sources import fetch_harness_changes, fetch_sources
    # Dry runs use a SQLite backup and never migrate/write the original database or artifacts.
    with tempfile.TemporaryDirectory() as temp:
        database = args.database
        if args.dry_run:
            database = str(Path(temp) / 'dry.sqlite3')
            if Path(args.database).exists():
                with sqlite3.connect(f'file:{Path(args.database).resolve()}?mode=ro', uri=True) as src, sqlite3.connect(database) as dest:
                    src.backup(dest)
        app = create_app({'DATABASE': database, 'APPLY_DATA_SNAPSHOT': False})
        with app.app_context():
            db = get_db()
            if args.command == 'validate':
                print(encode(validate(db)))
                return
            if args.base_snapshot:
                from .data_snapshot import apply_snapshot
                apply_snapshot(db, args.base_snapshot)
            records, failures, manifests = fetch_sources()
            now = datetime.now(timezone.utc).isoformat(timespec='seconds')
            try:
                report = update(db, records, failures, manifests, now)
                harnesses, harness_failures, harness_manifests = fetch_harness_changes()
                monitor_harnesses(db, harnesses, harness_failures, harness_manifests, report, now)
                db.commit()
            except Exception as error:
                if not args.dry_run:
                    evidence = {'failure_type': type(error).__name__, 'sources': failures, 'manifests': manifests,
                                'reviews': [dict(r) for r in db.execute("SELECT * FROM review_queue WHERE status='PENDING'")],
                                'rejected_observations': [dict(r) for r in db.execute('SELECT * FROM data_observations WHERE accepted=0')]}
                    digest = hashlib.sha256(encode(evidence).encode()).hexdigest()[:12]
                    path = Path(args.output_dir) / 'reports' / f'{now[:10]}-failed-{digest}.json'
                    atomic_write(path, encode(evidence) + '\n')
                    atomic_write(path.with_suffix('.md'), f'# Daily update failed — {now[:10]}\n\nNo data published. Failure type: {type(error).__name__}.\n\nSource failures and preserved review evidence: {path.name}\n')
                db.rollback()
                raise SystemExit('Update failed; no production data published. Inspect the preserved failure report.') from None
            if args.dry_run:
                print(encode({'dry_run': True, **report['records_changed'], 'validation': report['validation']}))
            else:
                print(encode(write_outputs(db, report, args.output_dir, now)))


if __name__ == '__main__':
    main()

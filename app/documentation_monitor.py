"""Fingerprint official plan, harness, workflow, and provider-offer sources.

This module records source revisions only. It never interprets documentation or
publishes capability, pricing, or allowance changes.
"""

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAX_BYTES = 8_000_000
TIMEOUT = 15


def monitored_sources(db):
    """Official URLs linked to plans, compatibility facts, or offer evidence."""
    ids = {r[0] for r in db.execute("SELECT source_id FROM plans WHERE source_id IS NOT NULL")}
    # First-party offer sources join the same change-review monitor. The monitor
    # flags source changes but never converts page text into a price or offer.
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='offers'").fetchone():
        ids.update(r[0] for r in db.execute("""SELECT DISTINCT x.source_id FROM offers x
          JOIN providers p ON p.id=x.provider_id WHERE x.source_id IS NOT NULL AND p.name!='OpenRouter'"""))
    for table in ("harness_claims", "harness_access_methods", "harness_mcp_capabilities",
                  "workflow_integrations", "workflow_harness_compatibility"):
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if not exists:
            continue
        cols = {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
        if "source_id" in cols:
            ids.update(r[0] for r in db.execute(f'SELECT DISTINCT source_id FROM "{table}" WHERE source_id IS NOT NULL'))
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    return [dict(r) for r in db.execute(
        f"SELECT id,name,url,source_type FROM sources WHERE id IN ({marks}) "
        "AND source_type IN ('official documentation','official pricing','official_docs','official_provider','official repository') "
        "ORDER BY id", tuple(sorted(ids))) if r["url"].startswith("https://")]


def _fetch(source):
    request = Request(source["url"], headers={"User-Agent": "UseThisModel-SourceMonitor/1.0", "Accept": "text/html,application/json;q=0.9,*/*;q=0.5"})
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                return source, None, None, response.status, "ResponseTooLarge"
            content_type = response.headers.get("Content-Type", "")
            text = body.decode(response.headers.get_content_charset() or "utf-8", "replace")
            # Fingerprint visible-ish text, independent of whitespace/template churn.
            normalized = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()
            content_hash = hashlib.sha256(normalized.encode()).hexdigest()
            if "json" in content_type.lower():
                try:
                    payload = json.loads(text)
                    schema = json.dumps(_json_shape(payload), sort_keys=True, separators=(",", ":"))
                except (ValueError, RecursionError):
                    schema = "invalid-json"
            else:
                schema = ",".join(sorted(set(re.findall(r"<([a-zA-Z][\w:-]*)\b", text))))
            schema_hash = hashlib.sha256((content_type.split(";")[0].lower() + ":" + schema).encode()).hexdigest()
            return source, content_hash, schema_hash, response.status, None
    except HTTPError as error:
        return source, None, None, error.code, "HTTPError"
    except (URLError, TimeoutError, OSError, UnicodeError):
        return source, None, None, None, "FetchError"


def _json_shape(value):
    if isinstance(value, dict):
        return {key: _json_shape(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_json_shape(value[0])] if value else []
    if value is None:
        return "null"
    return type(value).__name__


def monitor_documentation(db, now, max_sources=100, workers=8):
    """Check a bounded set of official sources; changes become review items."""
    sources = monitored_sources(db)[:max_sources]
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results.extend(pool.map(_fetch, sources))
    changes = failures = 0
    for source, content_hash, schema_hash, status_code, error_kind in results:
        previous = db.execute("SELECT * FROM documentation_monitor_state WHERE source_id=?", (source["id"],)).fetchone()
        status = "ERROR" if error_kind else "SCHEMA_CHANGED" if previous and previous["schema_hash"] and previous["schema_hash"] != schema_hash else "CHANGED" if previous and previous["content_hash"] and previous["content_hash"] != content_hash else "OK"
        changed = status in {"CHANGED", "SCHEMA_CHANGED"}
        if error_kind:
            failures += 1
        if changed:
            changes += 1
            from .data_update import review
            old = {"content_hash": previous["content_hash"], "schema_hash": previous["schema_hash"]} if previous else None
            review(db, {"Manual-review items": []}, now, f"documentation:{source['id']}", "source revision", old,
                   {"content_hash": content_hash, "schema_hash": schema_hash}, [source["url"]],
                   "Official source changed; offer, plan, or capability interpretation requires review",
                   f"HTTP {status_code}; content fingerprint changed", "HIGH")
        if error_kind:
            # Keep prior successful fingerprint and verification timestamp.
            db.execute("""INSERT INTO documentation_monitor_state(source_id,first_seen_at,last_checked_at,status,error_kind,http_status)
              VALUES(?,?,?,'ERROR',?,?) ON CONFLICT(source_id) DO UPDATE SET last_checked_at=excluded.last_checked_at,status='ERROR',error_kind=excluded.error_kind,http_status=excluded.http_status""",
              (source["id"], now, now, error_kind, status_code))
        else:
            db.execute("""INSERT INTO documentation_monitor_state(source_id,first_seen_at,last_checked_at,last_changed_at,last_verified_at,content_hash,schema_hash,status,error_kind,http_status)
              VALUES(?,?,?,?,?,?,?,?,NULL,?) ON CONFLICT(source_id) DO UPDATE SET last_checked_at=excluded.last_checked_at,
              last_changed_at=CASE WHEN excluded.status IN ('CHANGED','SCHEMA_CHANGED') THEN excluded.last_checked_at ELSE documentation_monitor_state.last_changed_at END,
              last_verified_at=CASE WHEN excluded.status='OK' THEN excluded.last_checked_at ELSE documentation_monitor_state.last_verified_at END,
              content_hash=excluded.content_hash,schema_hash=excluded.schema_hash,status=excluded.status,error_kind=NULL,http_status=excluded.http_status""",
              (source["id"], now, now, now if changed else None, now if not changed else None, content_hash, schema_hash, status, status_code))
        db.execute("UPDATE plans SET last_checked_at=?,last_verified_at=CASE WHEN ?='OK' THEN ? ELSE last_verified_at END,last_changed_at=CASE WHEN ? IN ('CHANGED','SCHEMA_CHANGED') THEN ? ELSE last_changed_at END WHERE source_id=?",
                   (now, status, now, status, now, source["id"]))
    return {"checked": len(results), "changed": changes, "failures": failures}

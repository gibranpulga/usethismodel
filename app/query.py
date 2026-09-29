"""Read-only catalogue queries used by the finder, table, and calculators."""

from __future__ import annotations

from datetime import date, timedelta


def _yes_capability(column: str) -> str:
    return f"EXISTS (SELECT 1 FROM offering_capabilities oc WHERE oc.offering_id=o.id AND oc.capability='{column}' AND oc.state='YES')"


def route_rows(db, filters=None):
    """Return provider routes.  Every filter is explicit and URL-safe."""
    filters = filters or {}
    try:
        limit = min(250, max(1, int(filters.get("limit", 100))))
    except (TypeError, ValueError):
        limit = 100
    clauses, params = ["1=1"], []
    q = filters.get("q", "").strip()
    if q:
        clauses.append("(lower(m.canonical_name) LIKE ? OR lower(o.api_model_id) LIKE ? OR lower(p.name) LIKE ? OR lower(COALESCE(l.name,m.vendor)) LIKE ?)")
        params += [f"%{q.lower()}%"] * 4
    for key, column in (("lab", "COALESCE(l.name,m.vendor)"), ("provider", "p.name"), ("type", "m.modality"), ("status", "m.status")):
        if filters.get(key) and filters[key] != "any":
            clauses.append(f"{column}=?")
            params.append(filters[key])
    if filters.get("release") == "week":
        clauses.append("m.released_at >= ?")
        params.append((date.today() - timedelta(days=7)).isoformat())
    for key, field in (("input_max", "input_price"), ("output_max", "output_price")):
        if filters.get(key):
            clauses.append(f"{field} IS NOT NULL AND {field} <= ?")
            params.append(float(filters[key]))
    for key, column in (("context", "o.context_limit"), ("max_output", "o.max_output_tokens")):
        if filters.get(key):
            clauses.append(f"{column} >= ?")
            params.append(int(filters[key]))
    if filters.get("free") == "1":
        clauses.append("o.free_status IN ('FREE','PROMOTIONAL') OR input_price=0")
    if filters.get("deal") == "1":
        clauses.append("EXISTS (SELECT 1 FROM offers x WHERE x.provider_id=p.id AND x.status='ACTIVE' AND (x.ends_at IS NULL OR x.ends_at>=date('now')))")
    if filters.get("subscription") == "1":
        clauses.append("EXISTS (SELECT 1 FROM plans pl WHERE pl.provider_id=p.id)")
    if filters.get("tools") == "1":
        clauses.append("o.tool_support='YES'")
    if filters.get("structured") == "1":
        clauses.append("o.structured_output_support='YES'")
    if filters.get("open_weights") == "1":
        clauses.append("m.open_weights=1")
    for key, capability in (("reasoning", "reasoning"), ("vision", "vision"), ("caching", "caching"), ("batch", "batch")):
        if filters.get(key) == "1":
            clauses.append(_yes_capability(capability))
    if filters.get("mcp") == "1":
        clauses.append("o.tool_support='YES'")
    if filters.get("use_case"):
        clauses.append("EXISTS (SELECT 1 FROM model_use_case_scores mus JOIN use_cases u ON u.id=mus.use_case_id WHERE mus.model_id=m.id AND u.slug=? AND mus.classification IN ('RECOMMENDED','SUPPORTED'))")
        params.append(filters["use_case"])
    access = filters.get("access")
    if access == "openrouter":
        clauses.append("p.name='OpenRouter'")
    elif access == "direct":
        clauses.append("p.name != 'OpenRouter'")
    elif access == "free":
        clauses.append("o.free_status IN ('FREE','PROMOTIONAL') OR input_price=0")
    sql = f"""
        SELECT o.id offering_id,o.api_model_id,o.context_limit,o.max_output_tokens,o.tool_support,
          o.structured_output_support,o.free_status,o.caveat,o.fetched_at,m.id model_id,
          m.canonical_name,m.canonical_slug,m.modality,m.open_weights,m.status,m.released_at,
          COALESCE(l.name,m.vendor) lab_name,p.id provider_id,p.name provider_name,
          (SELECT amount FROM pricing_records pr WHERE pr.offering_id=o.id AND pr.price_type='INPUT' AND pr.valid_until IS NULL ORDER BY pr.valid_from DESC,pr.id DESC LIMIT 1) input_price,
          (SELECT amount FROM pricing_records pr WHERE pr.offering_id=o.id AND pr.price_type='OUTPUT' AND pr.valid_until IS NULL ORDER BY pr.valid_from DESC,pr.id DESC LIMIT 1) output_price,
          (SELECT amount FROM pricing_records pr WHERE pr.offering_id=o.id AND pr.price_type='CACHE_READ' AND pr.valid_until IS NULL ORDER BY pr.valid_from DESC,pr.id DESC LIMIT 1) cache_read_price,
          {_yes_capability('reasoning')} reasoning, {_yes_capability('vision')} vision,
          {_yes_capability('caching')} caching, {_yes_capability('batch')} batch,
          EXISTS (SELECT 1 FROM offers x WHERE x.provider_id=p.id AND x.status='ACTIVE' AND (x.ends_at IS NULL OR x.ends_at>=date('now'))) active_deal
        FROM provider_offerings o JOIN models m ON m.id=o.model_id JOIN providers p ON p.id=o.provider_id
          LEFT JOIN labs l ON l.id=m.lab_id
        WHERE {' AND '.join(clauses)}
        ORDER BY input_price IS NULL, input_price, output_price, m.canonical_name, p.name
        LIMIT ?
    """
    return [dict(row) for row in db.execute(sql, [*params, limit]).fetchall()]


def filter_options(db):
    return {
        "labs": [r[0] for r in db.execute("SELECT name FROM labs ORDER BY name")],
        "providers": [r[0] for r in db.execute("SELECT name FROM providers ORDER BY name")],
        "types": [r[0] for r in db.execute("SELECT DISTINCT modality FROM models ORDER BY modality")],
        "use_cases": [dict(r) for r in db.execute("SELECT slug,name FROM use_cases ORDER BY name")],
        "harnesses": [dict(r) for r in db.execute("SELECT id,name FROM harnesses ORDER BY name")],
    }


def source_rows(db, offering_id=None, model_id=None):
    where, params = [], []
    if offering_id:
        where.append("(o.id=? OR pr.offering_id=? OR oc.offering_id=?)")
        params += [offering_id] * 3
    if model_id:
        where.append("(o.model_id=? OR br.model_id=?)")
        params += [model_id] * 2
    condition = " AND ".join(where) if where else "1=1"
    return [dict(r) for r in db.execute(f"""
      SELECT DISTINCT s.name,s.url,s.reliability FROM sources s
      LEFT JOIN provider_offerings o ON o.source_id=s.id LEFT JOIN pricing_records pr ON pr.source_id=s.id
      LEFT JOIN offering_capabilities oc ON oc.source_id=s.id LEFT JOIN benchmark_results br ON br.source_id=s.id
      WHERE {condition} ORDER BY s.name
    """, params).fetchall()]

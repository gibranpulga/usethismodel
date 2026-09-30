"""Read-only data-quality summaries and conservative review housekeeping."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

FRESHNESS_THRESHOLDS = {
    "pricing": (2, 7),
    "deals": (2, 7),
    "route_capabilities": (14, 30),
    "benchmarks": (30, 90),
    "plans": (7, 30),
    "harnesses": (14, 45),
    "workflows": (14, 45),
}

_KIND_ALIASES = {
    "price": "pricing",
    "prices": "pricing",
    "offer": "deals",
    "offers": "deals",
    "deal": "deals",
    "route_capability": "route_capabilities",
    "capability": "route_capabilities",
    "capabilities": "route_capabilities",
    "benchmark": "benchmarks",
    "plan": "plans",
    "harness": "harnesses",
    "workflow": "workflows",
}

_SAFE_REASONS = (
    "Legacy invalid price quarantined",
    "Legacy invalid token limit quarantined",
    "Invalid or unsupported structured value quarantined",
)


def freshness_thresholds(kind, current_publisher_version=False):
    """Return ``(fresh_days, stale_days)`` for a quality category.

    Current publisher benchmark versions are not aged out merely because the
    publisher has not changed them, so they have no finite thresholds.
    """
    normalized = _KIND_ALIASES.get(str(kind).lower(), str(kind).lower())
    if normalized not in FRESHNESS_THRESHOLDS:
        raise ValueError(f"Unknown freshness kind: {kind}")
    if normalized == "benchmarks" and current_publisher_version:
        return None, None
    return FRESHNESS_THRESHOLDS[normalized]


def freshness_label(kind, verified_at, now=None, current_publisher_version=False):
    """Classify an ISO timestamp as FRESH, AGING, STALE, or UNKNOWN."""
    verified = _datetime(verified_at)
    if verified is None:
        return "UNKNOWN"
    fresh_days, stale_days = freshness_thresholds(kind, current_publisher_version)
    if fresh_days is None:
        return "FRESH"
    current = _datetime(now) if now is not None else datetime.now(timezone.utc)
    if current is None:
        raise ValueError(f"Invalid current time: {now}")
    age = current - verified
    # A small amount of clock skew should not turn newly fetched data stale.
    days = max(0.0, age.total_seconds() / 86_400)
    if days <= fresh_days:
        return "FRESH"
    if days <= stale_days:
        return "AGING"
    return "STALE"


def freshness_text(kind, verified_at, now=None, current_publisher_version=False):
    """Human-readable verification age without implying that a value changed."""
    verified = _datetime(verified_at)
    if verified is None:
        return "Verification unknown"
    current = _datetime(now) if now is not None else datetime.now(timezone.utc)
    if current is None:
        raise ValueError(f"Invalid current time: {now}")
    seconds = max(0, int((current - verified).total_seconds()))
    label = freshness_label(kind, verified, current, current_publisher_version)
    if label == "STALE":
        return f"Stale: {seconds // 86_400} days"
    if seconds < 3_600:
        return f"Verified {max(1, seconds // 60)}m ago"
    if seconds < 86_400:
        return f"Verified {seconds // 3_600}h ago"
    if seconds < 172_800:
        return "Verified yesterday"
    return f"Verified {seconds // 86_400} days ago"


def source_health_rows(db):
    """Return source-health records in stable source-name order."""
    return [dict(row) for row in db.execute("SELECT * FROM source_health ORDER BY source")]


def review_triage(db):
    """Summarize pending review work without changing or hiding ambiguity."""
    counts = {}
    examples = {}
    for row in db.execute(
        "SELECT id,entity,proposed_change,triage_class,reason,evidence,sources,confidence,created_at "
        "FROM review_queue WHERE status='PENDING' ORDER BY id"
    ):
        triage_class = _triage_class(row["reason"])
        if triage_class == "other" and row["triage_class"]:
            triage_class = row["triage_class"]
        counts[triage_class] = counts.get(triage_class, 0) + 1
        examples.setdefault(triage_class, []).append(dict(row))
    groups = [
        {
            "triage_class": triage_class,
            "count": count,
            "auto_resolvable": triage_class == "quarantined_invalid_legacy",
            "evidence": examples[triage_class][:5],
        }
        for triage_class, count in sorted(counts.items())
    ]
    return {"pending_total": sum(counts.values()), "groups": groups}


def data_quality_metrics(db):
    """Return compact catalog-quality metrics for a generic dashboard."""
    routes = _count(db, "SELECT COUNT(*) FROM provider_offerings")
    priced = _count(
        db,
        """SELECT COUNT(*) FROM provider_offerings o
           WHERE EXISTS (SELECT 1 FROM pricing_records p WHERE p.offering_id=o.id
                         AND p.price_type='INPUT' AND p.valid_until IS NULL)
             AND EXISTS (SELECT 1 FROM pricing_records p WHERE p.offering_id=o.id
                         AND p.price_type='OUTPUT' AND p.valid_until IS NULL)""",
    )
    verified = _count(
        db, "SELECT COUNT(*) FROM provider_offerings WHERE last_verified_at IS NOT NULL"
    )
    verified_7d = _count(
        db, "SELECT COUNT(*) FROM provider_offerings WHERE last_verified_at>=datetime('now','-7 days')"
    )
    capabilities = _count(
        db,
        """SELECT COUNT(*) FROM provider_offerings
           WHERE tool_support!='UNKNOWN' AND structured_output_support!='UNKNOWN'""",
    )
    high_reliability = _count(
        db,
        """SELECT COUNT(*) FROM provider_offerings o JOIN sources s ON s.id=o.source_id
           WHERE s.reliability='HIGH'""",
    )
    benchmarks = _count(db, "SELECT COUNT(*) FROM benchmarks")
    current_benchmarks = _count(db, "SELECT COUNT(*) FROM benchmarks WHERE is_current=1")
    health_sources = _count(db, "SELECT COUNT(*) FROM source_health")
    healthy_sources = _count(db, "SELECT COUNT(*) FROM source_health WHERE status='OK'")
    pending = _count(db, "SELECT COUNT(*) FROM review_queue WHERE status='PENDING'")
    models = _count(db, "SELECT COUNT(*) FROM models")
    released = _count(db, "SELECT COUNT(*) FROM models WHERE released_at IS NOT NULL")
    harnesses = _count(db, "SELECT COUNT(*) FROM harnesses")
    providers = _count(db, "SELECT COUNT(*) FROM providers WHERE canonical_provider_id IS NULL")
    compatibility = _count(
        db,
        "SELECT COUNT(*) FROM harness_provider_compatibility WHERE support_mode!='UNKNOWN'",
    )
    active_deals = _count(
        db,
        """SELECT COUNT(*) FROM offers WHERE status='ACTIVE'
           AND (starts_at IS NULL OR starts_at<=date('now'))
           AND (ends_at IS NULL OR ends_at>=date('now'))""",
    )
    free_tools = _count(
        db,
        "SELECT COUNT(*) FROM provider_offerings WHERE access_semantics IN ('FREE_API','FREE_TIER') AND tool_support='YES'",
    )
    openrouter_free_tools = _count(
        db,
        "SELECT COUNT(*) FROM openrouter_route_variants WHERE is_free=1 AND endpoint_status=0 AND tool_support='YES'",
    )
    compat_harness_1 = _count(db, """SELECT COUNT(DISTINCT harness_id) FROM (
      SELECT harness_id FROM harness_provider_compatibility WHERE support_mode NOT IN ('UNKNOWN','NO')
      UNION SELECT harness_id FROM harness_access_methods WHERE access_method='OPENROUTER' AND state='YES')""")
    derived_provider_pairs = _count(db, "SELECT COUNT(DISTINCT harness_id) FROM harness_access_methods WHERE access_method='OPENROUTER' AND state='YES'")
    compat_harness_5 = _count(db, "SELECT COUNT(*) FROM (SELECT harness_id FROM harness_provider_compatibility WHERE support_mode NOT IN ('UNKNOWN','NO') GROUP BY harness_id HAVING COUNT(DISTINCT provider_id)>=5)")
    compat_route_evidence = _count(db, "SELECT COUNT(DISTINCT offering_id) FROM route_compatibility_evidence")
    compat_evidence_rows = _count(db, "SELECT COUNT(*) FROM route_compatibility_evidence")
    compat_workflow_rows = _count(db, "SELECT COUNT(*) FROM workflow_harness_compatibility")
    derived_openrouter_routes = _count(db, """SELECT COUNT(DISTINCT o.id) FROM provider_offerings o
      JOIN providers p ON p.id=o.provider_id JOIN harness_access_methods ha ON ha.access_method='OPENROUTER' AND ha.state='YES'
      WHERE p.name='OpenRouter'""")
    compat_unknown_route_pairs = _count(db, """SELECT COUNT(*) FROM provider_offerings o
      WHERE NOT EXISTS(SELECT 1 FROM route_compatibility_evidence e WHERE e.offering_id=o.id)
      AND NOT EXISTS(SELECT 1 FROM harness_provider_compatibility hpc WHERE hpc.provider_id=o.provider_id AND hpc.support_mode NOT IN ('UNKNOWN','NO'))
      AND NOT EXISTS(SELECT 1 FROM harness_access_methods ha JOIN providers p ON p.id=o.provider_id
        WHERE ha.harness_id IS NOT NULL AND ha.access_method='OPENROUTER' AND ha.state='YES' AND p.name='OpenRouter')""")

    return [
        _metric("routes", "Provider routes", routes),
        _metric("price_coverage", "Routes with input and output prices", priced, routes),
        _metric("verification_coverage", "Routes with verification dates", verified, routes),
        _metric("verified_7d", "Routes verified in the past 7 days", verified_7d, routes),
        _metric(
            "capability_coverage",
            "Routes with known tools and structured output",
            capabilities,
            routes,
        ),
        _metric(
            "first_party_route_coverage",
            "Routes backed by high-reliability sources",
            high_reliability,
            routes,
        ),
        _metric(
            "current_benchmark_coverage",
            "Current benchmark versions",
            current_benchmarks,
            benchmarks,
        ),
        _metric("release_date_coverage", "Models with release dates", released, models),
        _metric(
            "compatibility_coverage",
            "Harness/provider compatibility known",
            compatibility,
            harnesses * providers,
        ),
        _metric("harnesses_with_provider_integration", "Harnesses with >=1 provider integration", compat_harness_1, harnesses),
        _metric("derived_harness_provider_integrations", "Harness/provider pairs derivable from documented OpenRouter access", derived_provider_pairs),
        _metric("harnesses_with_five_integrations", "Harnesses with >=5 provider integrations", compat_harness_5, harnesses),
        _metric("routes_with_compatibility_evidence", "Routes with route-specific compatibility evidence", compat_route_evidence, routes),
        _metric("route_compatibility_evidence_rows", "Route-specific compatibility evidence rows", compat_evidence_rows),
        _metric("routes_with_derived_openrouter_compatibility", "OpenRouter routes eligible for evidence-derived harness compatibility", derived_openrouter_routes, routes),
        _metric("workflow_compatibility_evidence_rows", "Workflow-specific compatibility evidence rows", compat_workflow_rows),
        _metric("routes_unknown_without_provider_or_route_evidence", "Routes with no route/provider compatibility evidence", compat_unknown_route_pairs, routes),
        _metric("active_deals", "Active route/provider deals", active_deals),
        _metric("free_tool_routes", "Free tool-capable routes", free_tools),
        _metric(
            "openrouter_free_tool_endpoints",
            "Exact available OpenRouter free endpoints with tools",
            openrouter_free_tools,
        ),
        _metric("healthy_sources", "Healthy update sources", healthy_sources, health_sources),
        _metric("pending_reviews", "Pending review items", pending),
    ]


def auto_resolve_safe_reviews(db, now):
    """Resolve only proven quarantines; never resolve conflicting evidence.

    A rejected observation is required as evidence that the bad value was
    retained outside the selected catalog facts. If a selected fact points at
    any rejected observation for the same entity and field, the review remains
    pending even if its reason otherwise looks safe.
    """
    resolved = 0
    for row in db.execute(
        "SELECT id,entity,proposed_change,reason FROM review_queue "
        "WHERE status='PENDING' ORDER BY id"
    ).fetchall():
        if not _safe_reason(row["reason"]):
            continue
        rejected = db.execute(
            """SELECT 1 FROM data_observations
               WHERE entity=? AND field=? AND accepted=0 LIMIT 1""",
            (row["entity"], row["proposed_change"]),
        ).fetchone()
        selected_rejected = db.execute(
            """SELECT 1 FROM selected_facts sf
               JOIN data_observations observation ON observation.id=sf.observation_id
               WHERE sf.entity=? AND sf.field=? AND observation.accepted=0 LIMIT 1""",
            (row["entity"], row["proposed_change"]),
        ).fetchone()
        if not rejected or selected_rejected:
            continue
        result = db.execute(
            """UPDATE review_queue
               SET status='RESOLVED',resolved_at=?,
                   resolution_note='Auto-resolved: invalid value is quarantined as a rejected observation and is not selected.',
                   triage_class='quarantined_invalid_legacy'
               WHERE id=? AND status='PENDING'""",
            (now, row["id"]),
        )
        resolved += result.rowcount
    return resolved


def _datetime(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _triage_class(reason):
    reason = reason or ""
    if _safe_reason(reason):
        return "quarantined_invalid_legacy"
    lower = reason.lower()
    if "conflicting values within one source" in lower:
        return "same_source_conflict"
    if "ambiguous source aliases" in lower or "duplicated observation" in lower:
        return "duplicated_observation"
    if "sources disagree" in lower or "price increased by more than 10x" in lower or "pricing disagree" in lower:
        return "pricing_disagreement"
    if "canonical identity" in lower or "canonical id" in lower or "identity" in lower:
        return "identity"
    if "schema" in lower or "catalog collapsed" in lower or "provider disappeared" in lower:
        return "source_schema_change"
    if "route missing" in lower or "listing removed" in lower:
        return "route_removal"
    if "release date" in lower or "release_date" in lower:
        return "release_date"
    if "benchmark" in lower or "publisher result" in lower:
        return "benchmark"
    if "compatibility" in lower or "harness" in lower:
        return "compatibility"
    if "promotion" in lower or "offer" in lower:
        return "promotion"
    return "other"


def _safe_reason(reason):
    return any((reason or "").startswith(prefix) for prefix in _SAFE_REASONS)


def _count(db, query):
    return db.execute(query).fetchone()[0]


def _metric(key, label, numerator, denominator=None):
    if denominator is None:
        return {
            "key": key,
            "label": label,
            "value": numerator,
            "numerator": numerator,
            "denominator": None,
            "kind": "count",
        }
    value = round(100 * numerator / denominator, 1) if denominator else 0.0
    return {
        "key": key,
        "label": label,
        "value": value,
        "numerator": numerator,
        "denominator": denominator,
        "kind": "percent",
    }

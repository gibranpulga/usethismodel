"""Read-only data-quality summaries and conservative review housekeeping."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

FRESHNESS_THRESHOLDS = {
    "pricing": (2, 7),
    "deals": (2, 7),
    "route_capabilities": (14, 30),
    "benchmarks": (30, 90),
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
    for row in db.execute(
        "SELECT triage_class,reason FROM review_queue WHERE status='PENDING' ORDER BY id"
    ):
        triage_class = row["triage_class"] or _triage_class(row["reason"])
        counts[triage_class] = counts.get(triage_class, 0) + 1
    groups = [
        {
            "triage_class": triage_class,
            "count": count,
            "auto_resolvable": triage_class == "quarantined_invalid_legacy",
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
        "SELECT COUNT(*) FROM provider_offerings WHERE free_status='FREE' AND tool_support='YES'",
    )
    openrouter_free_tools = _count(
        db,
        "SELECT COUNT(*) FROM openrouter_route_variants WHERE is_free=1 AND endpoint_status=0 AND tool_support='YES'",
    )

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
    if reason.startswith("Conflicting values within one source"):
        return "within_source_conflict"
    if reason.startswith("Sources disagree") or reason.startswith("Price increased by more than 10x"):
        return "source_disagreement"
    if reason.startswith("Similar name has a different canonical ID"):
        return "identity_ambiguity"
    if reason.startswith("Route missing from successful source"):
        return "possible_route_removal"
    if reason.startswith("Legacy release date"):
        return "release_evidence_gap"
    if reason.startswith("Legacy benchmark score"):
        return "benchmark_evidence_gap"
    if reason.startswith("Official documentation changed"):
        return "harness_change"
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

import pytest

from app import create_app
from app.data_quality import (
    auto_resolve_safe_reviews,
    data_quality_metrics,
    freshness_label,
    freshness_text,
    freshness_thresholds,
    review_triage,
    source_health_rows,
)
from app.db import get_db


@pytest.fixture
def db(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "quality.sqlite3")})
    with app.app_context():
        yield get_db()


def test_freshness_thresholds_and_labels_include_current_benchmark_override():
    now = "2026-09-29T12:00:00+00:00"
    assert freshness_thresholds("pricing") == (2, 7)
    assert freshness_thresholds("deals") == (2, 7)
    assert freshness_thresholds("route_capability") == (14, 30)
    assert freshness_thresholds("benchmark") == (30, 90)
    assert freshness_label("pricing", "2026-09-28T12:00:00Z", now) == "FRESH"
    assert freshness_label("pricing", "2026-09-25T12:00:00Z", now) == "AGING"
    assert freshness_label("pricing", "2026-09-20T12:00:00Z", now) == "STALE"
    assert freshness_label("pricing", None, now) == "UNKNOWN"
    assert freshness_label("benchmark", "2020-01-01", now, True) == "FRESH"
    assert freshness_label("benchmark", None, now, True) == "UNKNOWN"
    assert freshness_text("pricing", "2026-09-29T10:00:00Z", now) == "Verified 2h ago"
    assert freshness_text("pricing", "2026-09-20T12:00:00Z", now) == "Stale: 9 days"


def test_source_health_and_quality_metrics_are_stable_query_shapes(db):
    db.executemany(
        """INSERT INTO source_health
           (source,source_url,last_attempt_at,last_success_at,status,records_imported)
           VALUES(?,?,?,?,?,?)""",
        [
            ("z-source", "https://z.test", "2026-09-29", None, "ERROR", 0),
            ("a-source", "https://a.test", "2026-09-29", "2026-09-29", "OK", 5),
        ],
    )
    rows = source_health_rows(db)
    assert [row["source"] for row in rows] == ["a-source", "z-source"]
    assert rows[0]["records_imported"] == 5

    metrics = {metric["key"]: metric for metric in data_quality_metrics(db)}
    assert metrics["routes"]["kind"] == "count"
    assert metrics["price_coverage"]["kind"] == "percent"
    assert metrics["healthy_sources"] == {
        "key": "healthy_sources",
        "label": "Healthy update sources",
        "value": 50.0,
        "numerator": 1,
        "denominator": 2,
        "kind": "percent",
    }


def test_review_triage_preserves_ambiguity_and_only_safe_quarantines_resolve(db):
    rejected = db.execute(
        """INSERT INTO data_observations
           (entity,field,source,source_url,value_json,priority,observed_at,accepted,evidence)
           VALUES('offering:1','input_price','fixture','https://fixture.test','-1',10,
                  '2026-09-29',0,'quarantined')"""
    ).lastrowid
    selected_rejected = db.execute(
        """INSERT INTO data_observations
           (entity,field,source,source_url,value_json,priority,observed_at,accepted,evidence)
           VALUES('offering:2','max_output_tokens','fixture','https://fixture.test','0',10,
                  '2026-09-29',0,'quarantined')"""
    ).lastrowid
    db.execute(
        "INSERT INTO selected_facts(entity,field,observation_id) VALUES(?,?,?)",
        ("offering:2", "max_output_tokens", selected_rejected),
    )
    rows = [
        (
            "safe",
            "offering:1",
            "input_price",
            "Legacy invalid price quarantined; original row preserved as evidence",
        ),
        (
            "selected-bad",
            "offering:2",
            "max_output_tokens",
            "Legacy invalid token limit quarantined",
        ),
        (
            "ambiguous",
            "offering:1",
            "input_price",
            "Sources disagree; displayed value follows precedence",
        ),
    ]
    for ident, entity, field, reason in rows:
        db.execute(
            """INSERT INTO review_queue
               (id,entity,proposed_change,sources,evidence,confidence,reason,created_at)
               VALUES(?,?,?,'[]','fixture','LOW',?,'2026-09-29')""",
            (ident, entity, field, reason),
        )

    triage = review_triage(db)
    assert triage["pending_total"] == 3
    assert {group["triage_class"] for group in triage["groups"]} == {
        "quarantined_invalid_legacy",
        "source_disagreement",
    }

    assert auto_resolve_safe_reviews(db, "2026-09-29T12:00:00+00:00") == 1
    statuses = dict(db.execute("SELECT id,status FROM review_queue"))
    assert statuses == {
        "safe": "RESOLVED",
        "selected-bad": "PENDING",
        "ambiguous": "PENDING",
    }
    safe = db.execute(
        "SELECT resolved_at,resolution_note,triage_class FROM review_queue WHERE id='safe'"
    ).fetchone()
    assert safe["resolved_at"] == "2026-09-29T12:00:00+00:00"
    assert "not selected" in safe["resolution_note"]
    assert safe["triage_class"] == "quarantined_invalid_legacy"
    assert rejected

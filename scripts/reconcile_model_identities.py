"""Audit and apply exact, unambiguous provider identity matches.

Only an identical API model ID already present on another provider route can
be accepted automatically. Names are reported as candidates, never merged.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import date
from pathlib import Path

TODAY = date.today().isoformat()
DEFAULT_AUDIT = Path("data/reports/canonical-model-identity-audit-2026-09-30.json")


def counts(db):
    return {
        "canonical_models": db.execute("SELECT COUNT(*) FROM models").fetchone()[0],
        "provider_routes": db.execute("SELECT COUNT(*) FROM provider_offerings").fetchone()[0],
        "duplicate_canonical_name_groups": db.execute(
            """SELECT COUNT(*) FROM (SELECT lower(canonical_name) FROM models
               GROUP BY lower(canonical_name) HAVING COUNT(*) > 1)"""
        ).fetchone()[0],
        "unresolved_provider_identities": db.execute(
            """SELECT COUNT(DISTINCT o.id) FROM provider_offerings o
               JOIN models m ON m.id=o.model_id WHERE m.identity_kind='UNKNOWN'"""
        ).fetchone()[0],
        "accepted_mappings": db.execute(
            "SELECT COUNT(*) FROM model_identity_mappings WHERE status='ACCEPTED'"
        ).fetchone()[0],
        "pending_mappings": db.execute(
            "SELECT COUNT(*) FROM model_identity_mappings WHERE status='PENDING'"
        ).fetchone()[0],
    }


def route_details(db, model_ids):
    if not model_ids:
        return []
    marks = ",".join("?" for _ in model_ids)
    return [
        dict(row)
        for row in db.execute(
            f"""SELECT o.id offering_id,o.provider_id,p.name provider,o.api_model_id,m.canonical_slug,
                       s.name source,s.url evidence_url
                FROM provider_offerings o JOIN providers p ON p.id=o.provider_id
                JOIN models m ON m.id=o.model_id LEFT JOIN sources s ON s.id=o.source_id
                WHERE m.id IN ({marks}) ORDER BY p.name,o.api_model_id""",
            tuple(model_ids),
        )
    ]


def route_details_by_offerings(db, offering_ids):
    if not offering_ids:
        return []
    marks = ",".join("?" for _ in offering_ids)
    return [
        dict(row)
        for row in db.execute(
            f"""SELECT o.id offering_id,o.provider_id,p.name provider,o.api_model_id,m.canonical_slug,
                       s.name source,s.url evidence_url
                FROM provider_offerings o JOIN providers p ON p.id=o.provider_id
                JOIN models m ON m.id=o.model_id LEFT JOIN sources s ON s.id=o.source_id
                WHERE o.id IN ({marks}) ORDER BY p.name,o.api_model_id""",
            tuple(offering_ids),
        )
    ]


def exact_candidates(db, api_model_id, current_model_id):
    return [
        dict(row)
        for row in db.execute(
            """SELECT DISTINCT m.id model_id,m.canonical_name,m.canonical_slug,m.identity_kind
               FROM provider_offerings o JOIN models m ON m.id=o.model_id
               WHERE lower(o.api_model_id)=lower(?) AND m.id<>? AND m.identity_kind<>'UNKNOWN'
               ORDER BY m.canonical_slug""",
            (api_model_id, current_model_id),
        )
    ]


def name_candidates(db, canonical_name, current_model_id):
    return [
        dict(row)
        for row in db.execute(
            """SELECT id model_id,canonical_name,canonical_slug,identity_kind FROM models
               WHERE lower(canonical_name)=lower(?) AND id<>? AND identity_kind<>'UNKNOWN'
               ORDER BY canonical_slug""",
            (canonical_name, current_model_id),
        )
    ]


def evidence_for_candidate(db, api_model_id, candidate_id):
    return [
        dict(row)
        for row in db.execute(
            """SELECT o.id offering_id,o.provider_id,m.id model_id,p.name provider,o.api_model_id,
                      s.name source,s.source_type,s.url
               FROM provider_offerings o JOIN providers p ON p.id=o.provider_id
               JOIN models m ON m.id=o.model_id
               LEFT JOIN sources s ON s.id=o.source_id
               WHERE o.model_id=? AND lower(o.api_model_id)=lower(?)
               ORDER BY CASE WHEN s.source_type LIKE 'official%' THEN 0
                             WHEN p.name='OpenRouter' THEN 1 ELSE 2 END,p.name""",
            (candidate_id, api_model_id),
        )
    ]


def route_evidence(db, routes):
    details = []
    for route in routes:
        offering_id = route["offering_id"]
        observations = [
            dict(row)
            for row in db.execute(
                """SELECT d.source,d.source_url,group_concat(DISTINCT d.field) fields,COUNT(*) count
                   FROM data_observations d WHERE d.entity=?
                   GROUP BY d.source,d.source_url ORDER BY d.source""",
                (f"offering:{offering_id}",),
            )
        ]
        identity_observations = [dict(row) for row in db.execute(
            """SELECT d.field,d.source,d.source_url,d.value_json,d.evidence FROM data_observations d
               WHERE d.entity=? AND (lower(d.field) LIKE '%identity%' OR lower(d.field) LIKE '%canonical%')
               ORDER BY d.id""",
            (f"offering:{offering_id}",),
        )]
        aliases = [
            dict(row)
            for row in db.execute(
                """SELECT a.alias,p.name provider,s.name source,s.url evidence_url
                   FROM model_aliases a LEFT JOIN providers p ON p.id=a.provider_id
                   LEFT JOIN sources s ON s.id=a.source_id WHERE a.model_id=? AND a.provider_id=?
                     AND lower(a.alias)=lower(?) ORDER BY p.name""",
                (route["model_id"], route["provider_id"], route["api_model_id"]),
            )
        ]
        variants = [
            dict(row)
            for row in db.execute(
                """SELECT provider_tag,route_name,endpoint_status,source_url
                   FROM openrouter_route_variants WHERE offering_id=? ORDER BY provider_tag""",
                (offering_id,),
            )
        ]
        details.append(
            {
                **route,
                "matching_alias_evidence": aliases,
                "observation_count": sum(item["count"] for item in observations),
                "observation_sources": [
                    {**item, "fields": sorted(filter(None, item["fields"].split(",")))}
                    for item in observations
                ],
                "identity_specific_observations": identity_observations,
                "openrouter_route_variants": variants,
            }
        )
    return details


def apply_exact_mapping(db, unresolved, candidate, evidence):
    provider_id = unresolved["provider_id"]
    provider_model_id = unresolved["provider_model_id"]
    source_url = next((row["url"] for row in evidence if row["url"]), "")
    source_id = db.execute("SELECT id FROM sources WHERE url=? LIMIT 1", (source_url,)).fetchone()
    confidence = "HIGH" if any(
        row["source_type"] and row["source_type"].startswith("official") for row in evidence
    ) else "MEDIUM"
    evidence_text = (
        f"Exact provider model ID {provider_model_id!r} appears on the unresolved "
        f"{unresolved['provider_name']} route and on {', '.join(sorted({r['provider'] for r in evidence}))}; "
        f"all matching source routes resolve to canonical model {candidate['canonical_slug']!r}. "
        "No name similarity or model-family inference was used."
    )
    db.execute(
        """INSERT INTO model_identity_mappings(provider_id,provider_model_id,model_id,
             evidence_source_id,evidence_url,evidence,confidence,status,verified_at)
           VALUES(?,?,?,?,?,?,?,'ACCEPTED',?)
           ON CONFLICT(provider_id,provider_model_id) DO UPDATE SET
             model_id=excluded.model_id,evidence_source_id=excluded.evidence_source_id,
             evidence_url=excluded.evidence_url,evidence=excluded.evidence,
             confidence=excluded.confidence,status='ACCEPTED',verified_at=excluded.verified_at""",
        (
            provider_id,
            provider_model_id,
            candidate["model_id"],
            source_id[0] if source_id else None,
            source_url,
            evidence_text,
            confidence,
            TODAY,
        ),
    )
    db.execute(
        "UPDATE provider_offerings SET model_id=? WHERE provider_id=? AND api_model_id=?",
        (candidate["model_id"], provider_id, provider_model_id),
    )
    # Keep route aliases and their source IDs, but make their lookup point at the
    # newly accepted canonical model. The alias row itself is the provenance.
    db.execute(
        "UPDATE model_aliases SET model_id=? WHERE provider_id=? AND lower(alias)=lower(?)",
        (candidate["model_id"], provider_id, provider_model_id),
    )
    db.execute(
        """UPDATE model_identity_review SET status='RESOLVED',candidate_model_id=?
           WHERE provider_id=? AND provider_model_id=? AND status='PENDING'""",
        (candidate["model_id"], provider_id, provider_model_id),
    )


def merge_exact_duplicate_groups(db):
    """Merge only duplicate-name rows tied by one exact OpenRouter route ID."""
    router = db.execute("SELECT id FROM providers WHERE name='OpenRouter'").fetchone()
    if not router:
        return []
    groups = db.execute(
        """SELECT lower(canonical_name) name_key,COUNT(*) model_count FROM models
           GROUP BY lower(canonical_name) HAVING COUNT(*)>1 ORDER BY lower(canonical_name)"""
    ).fetchall()
    merges = []
    for group in groups:
        models = [
            dict(row)
            for row in db.execute(
                """SELECT id,canonical_name,canonical_slug FROM models
                   WHERE lower(canonical_name)=? ORDER BY canonical_slug""",
                (group["name_key"],),
            )
        ]
        router_routes = [
            dict(row)
            for row in db.execute(
                """SELECT o.model_id,o.api_model_id,o.source_id,s.url FROM provider_offerings o
                   LEFT JOIN sources s ON s.id=o.source_id
                   WHERE o.provider_id=? AND o.model_id IN (""" + ",".join("?" for _ in models) + ")",
                (router[0], *(model["id"] for model in models)),
            )
        ]
        router_targets = {item["model_id"] for item in router_routes}
        route_ids = {item["api_model_id"].lower() for item in router_routes}
        if len(router_targets) != 1:
            continue
        target_id = next(iter(router_targets))
        for old in models:
            old_id = old["id"]
            if old_id == target_id:
                continue
            router_route = next(
                (item for item in router_routes if item["api_model_id"].lower() in route_ids),
                None,
            )
            proof = len(route_ids) == 1 and db.execute(
                """SELECT 1 FROM provider_offerings WHERE model_id=?
                   AND lower(api_model_id)=? LIMIT 1""",
                (old_id, next(iter(route_ids)) if route_ids else ""),
            ).fetchone()
            classification = "A"
            evidence_source_id = router_route["source_id"] if router_route else None
            evidence_url = router_route["url"] if router_route else ""
            matched_alias = None
            if not proof:
                alias_targets = [
                    dict(row)
                    for row in db.execute(
                        """SELECT DISTINCT m.id model_id,m.canonical_slug,a.source_id,s.url
                           FROM model_aliases a JOIN models m ON m.id=a.model_id
                           JOIN sources s ON s.id=a.source_id
                           WHERE m.id=? AND lower(a.alias)=lower(?) AND s.url<>''""",
                        (target_id, old["canonical_slug"]),
                    )
                ]
                if len(alias_targets) != 1 or not router_route:
                    continue
                classification = "B"
                matched_alias = alias_targets[0]
                evidence_source_id = matched_alias["source_id"]
                evidence_url = matched_alias["url"]
            conflicts = [
                ("provider_offerings", "provider_id AND api_model_id"),
                ("model_aliases", "provider_id AND alias"),
                ("model_use_case_scores", "use_case_id AND source_id"),
                ("routes", "provider_id"),
            ]
            blocked = False
            for table, keys in conflicts:
                on = " AND ".join(f"a.{key.strip()}=b.{key.strip()}" for key in keys.split(" AND "))
                left_key = "model_id" if table != "routes" else "model_id"
                if db.execute(
                    f"SELECT 1 FROM {table} a JOIN {table} b ON {on} "
                    f"WHERE a.{left_key}=? AND b.{left_key}=? LIMIT 1",
                    (old_id, target_id),
                ).fetchone():
                    blocked = True
                    break
            if blocked:
                continue
            if db.execute(
                """SELECT 1 FROM model_media_features a JOIN model_media_features b ON 1=1
                   WHERE a.model_id=? AND b.model_id=?""",
                (old_id, target_id),
            ).fetchone():
                continue
            # The target slug itself is the identity advertised by OpenRouter;
            # matching exact route IDs provide the merge link.
            evidence_url = evidence_url or "https://openrouter.ai/api/v1/models"
            if classification == "A":
                evidence_text = (
                    f"Exact OpenRouter route ID {router_route['api_model_id']!r} is present on both "
                    f"{old['canonical_slug']!r} and {db.execute('SELECT canonical_slug FROM models WHERE id=?', (target_id,)).fetchone()[0]!r}; "
                    "the OpenRouter-backed canonical model is retained."
                )
            else:
                evidence_text = (
                    f"Source-backed alias {old['canonical_slug']!r} points to "
                    f"{db.execute('SELECT canonical_slug FROM models WHERE id=?', (target_id,)).fetchone()[0]!r}; "
                    "the alias target has an OpenRouter canonical route."
                )
            db.execute(
                """INSERT INTO model_identity_redirects(old_model_id,old_slug,old_name,target_model_id,
                     evidence_source_id,evidence_url,evidence,verified_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (old_id, old["canonical_slug"], old["canonical_name"], target_id,
                 evidence_source_id, evidence_url, evidence_text, TODAY),
            )
            db.execute("UPDATE provider_offerings SET model_id=? WHERE model_id=?", (target_id, old_id))
            db.execute("UPDATE model_aliases SET model_id=? WHERE model_id=?", (target_id, old_id))
            for table in (
                "routes", "benchmark_measurements", "benchmark_results", "harness_model_overrides",
                "model_use_case_scores", "model_media_features", "model_identity_mappings",
            ):
                db.execute(f"UPDATE {table} SET model_id=? WHERE model_id=?", (target_id, old_id))
            db.execute("UPDATE model_identity_review SET candidate_model_id=? WHERE candidate_model_id=?",
                       (target_id, old_id))
            db.execute("DELETE FROM models WHERE id=?", (old_id,))
            merges.append({
                "old_model_id": old_id,
                "classification": classification,
                "old_slug": old["canonical_slug"],
                "target_model_id": target_id,
                "target_slug": db.execute("SELECT canonical_slug FROM models WHERE id=?", (target_id,)).fetchone()[0],
                "identity_evidence": evidence_text,
                "evidence_url": evidence_url,
                "verified_at": TODAY,
            })
    return merges


def run(db, audit_path):
    before = counts(db)
    unresolved_rows = [
        dict(row)
        for row in db.execute(
            """SELECT p.id provider_id,p.name provider_name,o.id offering_id,
                      o.api_model_id provider_model_id,m.id current_model_id,
                      m.canonical_name current_canonical_name,m.canonical_slug current_canonical_slug,
                      (SELECT s.url FROM sources s WHERE s.id=o.source_id) route_source_url
               FROM provider_offerings o JOIN providers p ON p.id=o.provider_id
               JOIN models m ON m.id=o.model_id WHERE m.identity_kind='UNKNOWN'
               ORDER BY p.name,o.api_model_id"""
        )
    ]
    audit_rows = []
    accepted_count = 0
    for unresolved in unresolved_rows:
        candidates = exact_candidates(db, unresolved["provider_model_id"], unresolved["current_model_id"])
        candidate_basis = "identical_provider_model_id"
        if len(candidates) > 1:
            openrouter_candidates = [
                candidate
                for candidate in candidates
                if db.execute(
                    """SELECT 1 FROM provider_offerings o JOIN providers p ON p.id=o.provider_id
                       WHERE p.name='OpenRouter' AND o.model_id=? AND lower(o.api_model_id)=lower(?)
                       LIMIT 1""",
                    (candidate["model_id"], unresolved["provider_model_id"]),
                ).fetchone()
            ]
            if len(openrouter_candidates) == 1:
                candidates = openrouter_candidates
                candidate_basis = "openrouter_canonical_upstream_identity"
        if not candidates:
            candidates = name_candidates(
                db, unresolved["current_canonical_name"], unresolved["current_model_id"]
            )
            candidate_basis = "exact_canonical_name_only"
        route_candidates = []
        for candidate in candidates:
            candidate["matching_routes"] = evidence_for_candidate(
                db, unresolved["provider_model_id"], candidate["model_id"]
            )
            candidate["matching_routes_evidence"] = route_evidence(db, candidate["matching_routes"])
            lab = db.execute(
                """SELECT l.name,l.source_id,s.name source,s.url FROM models m
                   LEFT JOIN labs l ON l.id=m.lab_id LEFT JOIN sources s ON s.id=l.source_id
                   WHERE m.id=?""",
                (candidate["model_id"],),
            ).fetchone()
            candidate["lab_evidence"] = dict(lab) if lab else None
            route_candidates.append(candidate)

        exact_proof = candidate_basis in {
            "identical_provider_model_id",
            "openrouter_canonical_upstream_identity",
        } and len(candidates) == 1
        reason = (
            "Exact provider ID has one canonical target across observed provider routes."
            if exact_proof
            else "No exact-ID route match; exact-name matches are candidates only."
            if candidate_basis == "exact_canonical_name_only" and candidates
            else "Exact provider ID appears under multiple canonical targets."
            if candidates
            else "No exact-ID or exact-name candidate is present in current source-backed catalog data."
        )
        if exact_proof:
            apply_exact_mapping(db, unresolved, candidates[0], candidates[0]["matching_routes"])
            accepted_count += 1
        elif len(candidates) == 1:
            candidate_id = candidates[0]["model_id"]
            confidence = "MEDIUM"
            target = candidates[0]
            db.execute(
                """INSERT INTO model_identity_mappings(provider_id,provider_model_id,model_id,
                     evidence_url,evidence,confidence,status,verified_at)
                   VALUES(?,?,?,?,?,?,'PENDING',NULL)
                   ON CONFLICT(provider_id,provider_model_id) DO NOTHING""",
                (
                    unresolved["provider_id"],
                    unresolved["provider_model_id"],
                    candidate_id,
                    unresolved["route_source_url"] or "",
                    f"Candidate {target['canonical_slug']!r} shares only an exact display name; "
                    "identity equivalence is not established.",
                    confidence,
                ),
            )
            db.execute(
                """UPDATE model_identity_review SET candidate_model_id=?,reason=?
                   WHERE provider_id=? AND provider_model_id=? AND status='PENDING'""",
                (candidate_id, reason, unresolved["provider_id"], unresolved["provider_model_id"]),
            )
        else:
            db.execute(
                """UPDATE model_identity_review SET candidate_model_id=NULL,reason=?
                   WHERE provider_id=? AND provider_model_id=? AND status='PENDING'""",
                (reason, unresolved["provider_id"], unresolved["provider_model_id"]),
            )

        audit_rows.append(
            {
                "provider": unresolved["provider_name"],
                "provider_id": unresolved["provider_id"],
                "provider_model_id": unresolved["provider_model_id"],
                "current_canonical_model": {
                    "id": unresolved["current_model_id"],
                    "name": unresolved["current_canonical_name"],
                    "slug": unresolved["current_canonical_slug"],
                },
                "candidate_canonical_models": [
                    {
                        "id": candidate["model_id"],
                        "name": candidate["canonical_name"],
                        "slug": candidate["canonical_slug"],
                        "candidate_basis": candidate_basis,
                        "matching_provider_routes": candidate["matching_routes"],
                        "affected_provider_routes": candidate["matching_routes_evidence"],
                        "lab_evidence": candidate["lab_evidence"],
                    }
                    for candidate in candidates
                ],
                "exact_evidence_available": [
                    {
                        "kind": "identical_provider_model_id",
                        "provider": route["provider"],
                        "api_model_id": route["api_model_id"],
                        "source": route["source"],
                        "source_type": route["source_type"],
                        "evidence_url": route["url"],
                        "identity_specific_observations": route["identity_specific_observations"],
                        "matching_alias_evidence": route["matching_alias_evidence"],
                        "openrouter_route_variants": route["openrouter_route_variants"],
                    }
                    for candidate in candidates
                    for route in candidate["matching_routes_evidence"]
                ],
                "ambiguity_reason": reason,
                "affected_provider_routes": route_details_by_offerings(
                    db,
                    [
                        unresolved["offering_id"],
                        *[
                            route["offering_id"]
                            for candidate in candidates
                            for route in candidate["matching_routes"]
                        ],
                    ],
                ),
                "confidence": "HIGH" if exact_proof else "MEDIUM" if candidates else "LOW",
                "mapping_status": "ACCEPTED" if exact_proof else "PENDING" if len(candidates) == 1 else "UNRESOLVED",
            }
        )

    duplicate_groups = []
    merges = merge_exact_duplicate_groups(db)
    duplicates = db.execute(
        """SELECT lower(canonical_name) normalized_name,MIN(canonical_name) name,
                  group_concat(id) model_ids,group_concat(canonical_slug,' | ') slugs,
                  COUNT(*) model_count FROM models GROUP BY lower(canonical_name)
           HAVING COUNT(*)>1 ORDER BY lower(canonical_name)"""
    ).fetchall()
    for row in duplicates:
        model_ids = [int(value) for value in row["model_ids"].split(",")]
        routes = route_details(db, model_ids)
        slugs = [item["canonical_slug"] for item in db.execute(
            "SELECT canonical_slug FROM models WHERE id IN (" + ",".join("?" for _ in model_ids) + ")",
            model_ids,
        )]
        has_version_tokens = all(
            re.search(r"(?:20\d{2}[-.]?\d{2}(?:[-.]?\d{2})?|(?:^|[-/])v\d+(?:\.\d+)+)", slug, re.I)
            for slug in slugs
        )
        duplicate_groups.append(
            {
                "name": row["name"],
                "model_count": row["model_count"],
                "models": [dict(item) for item in db.execute(
                    "SELECT id,canonical_name,canonical_slug,identity_kind FROM models WHERE id IN (" +
                    ",".join("?" for _ in model_ids) + ") ORDER BY canonical_slug", model_ids
                )],
                "provider_routes": routes,
                "classification": "C" if has_version_tokens else "D",
                "classification_reason": (
                    "Canonical IDs contain distinct explicit version/date identifiers; keep releases separate."
                    if has_version_tokens else
                    "Duplicate display names alone do not prove identity equivalence; no exact alias or canonical route resolves the group."
                ),
            }
        )

    after = counts(db)
    report = {
        "generated_at": TODAY,
        "method": "Exact case-insensitive provider model ID matches with one canonical target, or an exact OpenRouter canonical/upstream route; no fuzzy matching.",
        "before": before,
        "after": after,
        "mappings_accepted_this_run": accepted_count,
        "models_merged_this_run": len(merges),
        "safe_model_merges": merges,
        "duplicate_classification_counts": {
            "A": sum(item["classification"] == "A" for item in merges),
            "B": sum(item["classification"] == "B" for item in merges),
            "C": sum(item["classification"] == "C" for item in duplicate_groups),
            "D": sum(item["classification"] == "D" for item in duplicate_groups),
        },
        "models_merged_total": db.execute("SELECT COUNT(*) FROM model_identity_redirects").fetchone()[0],
        "routes_preserved_by_model_merges": db.execute("SELECT COUNT(*) FROM provider_offerings").fetchone()[0],
        "unresolved_provider_identities": audit_rows,
        "duplicate_canonical_name_groups": duplicate_groups,
        "duplicate_groups_classified_as_unresolved": len(duplicate_groups),
        "ambiguous_cases_intentionally_left_unresolved": sum(
            item["mapping_status"] == "UNRESOLVED" for item in audit_rows
        ),
        "routes_preserved": after["provider_routes"],
        "source_inventory": {
            "labs": db.execute("SELECT COUNT(*) FROM labs").fetchone()[0],
            "model_aliases": db.execute("SELECT COUNT(*) FROM model_aliases").fetchone()[0],
            "data_observations": db.execute("SELECT COUNT(*) FROM data_observations").fetchone()[0],
            "openrouter_route_variants": db.execute("SELECT COUNT(*) FROM openrouter_route_variants").fetchone()[0],
            "models_dev_observations": db.execute(
                "SELECT COUNT(*) FROM data_observations WHERE source='models.dev'"
            ).fetchone()[0],
            "litellm_observations": db.execute(
                "SELECT COUNT(*) FROM data_observations WHERE source='litellm'"
            ).fetchone()[0],
            "provider_qualified_unknown_ids": sum("/" in item["provider_model_id"] for item in audit_rows),
            "identity_specific_data_observations": db.execute(
                """SELECT COUNT(*) FROM data_observations WHERE lower(field) LIKE '%identity%'
                   OR lower(field) LIKE '%canonical%'"""
            ).fetchone()[0],
        },
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="instance/usethismodel.sqlite3")
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    args = parser.parse_args()
    db = sqlite3.connect(args.database)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    result = run(db, args.audit)
    db.commit()
    print(json.dumps({"before": result["before"], "after": result["after"],
                      "accepted_this_run": result["mappings_accepted_this_run"],
                      "ambiguous_left_unresolved": result["ambiguous_cases_intentionally_left_unresolved"]},
                     sort_keys=True))
    db.close()


if __name__ == "__main__":
    main()

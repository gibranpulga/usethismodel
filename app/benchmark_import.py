"""Strict adapter for publisher-backed structured benchmark exports.

The adapter intentionally does not fetch or scrape publisher pages. Callers must
provide a reproducible structured export and its source URL. Missing run metadata
is retained as SQL NULL rather than inferred.
"""

import hashlib
import json
import math

REQUIRED = {"benchmark_name", "benchmark_version", "model_id", "score", "metric",
            "source_url", "evaluated_at"}
OPTIONAL = ("offering_id", "model_version", "harness_name", "harness_version", "scaffold",
            "reasoning_setting", "tool_policy", "network_policy", "task_subset", "attempts_per_task",
            "step_budget", "token_budget", "time_budget_seconds", "grader_version",
            "confidence_interval", "confidence", "input_tokens", "cached_input_tokens",
            "cache_write_tokens", "answer_tokens", "reasoning_tokens", "total_output_tokens",
            "model_cost_usd", "infrastructure_cost_usd", "cost_per_task_usd", "wall_time_seconds",
            "pricing_snapshot_at", "telemetry_complete")


def import_publisher_results(db, records):
    """Insert new exact-version rows without overwriting published history.

    Repeated imports are idempotent. A changed score for the same published
    run creates a review item and preserves the previously accepted value.
    """
    inserted = 0
    for record in records:
        missing = REQUIRED - record.keys()
        if missing:
            raise ValueError("Missing benchmark fields: " + ", ".join(sorted(missing)))
        benchmark = db.execute("SELECT id FROM benchmarks WHERE name=? AND version=?",
                               (record["benchmark_name"], record["benchmark_version"])).fetchone()
        if not benchmark:
            raise ValueError("Benchmark name/version is not registered")
        if not db.execute("SELECT 1 FROM sources WHERE url=?", (record["source_url"],)).fetchone():
            raise ValueError("Publisher source URL is not registered")
        source_id = db.execute("SELECT id FROM sources WHERE url=?", (record["source_url"],)).fetchone()[0]
        if not db.execute("SELECT 1 FROM models WHERE id=?", (record["model_id"],)).fetchone():
            raise ValueError("Unknown canonical model id")
        try:
            score = float(record["score"])
        except (TypeError, ValueError) as error:
            raise ValueError("Benchmark score must be numeric") from error
        if not math.isfinite(score):
            raise ValueError("Benchmark score must be finite")
        if record.get("confidence", "UNKNOWN") not in {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}:
            raise ValueError("Invalid benchmark confidence")
        keys = ("benchmark_id", "model_id", "offering_id", "model_version", "score", "metric",
                "harness_name", "harness_version", "scaffold", "reasoning_setting", "task_subset",
                "tool_policy", "network_policy", "step_budget", "token_budget", "time_budget_seconds",
                "attempts_per_task", "grader_version", "confidence_interval", "evaluated_at", "source_id",
                "confidence", "input_tokens", "cached_input_tokens", "cache_write_tokens", "answer_tokens",
                "reasoning_tokens", "total_output_tokens", "model_cost_usd", "infrastructure_cost_usd",
                "cost_per_task_usd", "wall_time_seconds", "pricing_snapshot_at", "telemetry_complete")
        values = {**record, "benchmark_id": benchmark[0], "source_id": source_id}
        values["telemetry_complete"] = int(bool(record.get("telemetry_complete", False)))
        identity_keys = ("benchmark_id", "model_id", "model_version", "metric", "harness_name",
                         "harness_version", "scaffold", "reasoning_setting", "task_subset",
                         "tool_policy", "network_policy", "evaluated_at", "source_id")
        where = " AND ".join(f"{key} IS ?" for key in identity_keys)
        previous = db.execute(f"SELECT id,score FROM benchmark_results WHERE {where} LIMIT 1",
                              [values.get(key) for key in identity_keys]).fetchone()
        if previous:
            if float(previous["score"]) != score:
                evidence = {"record": record, "existing_result_id": previous["id"],
                            "existing_score": previous["score"]}
                review_id = hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest()[:24]
                db.execute("""INSERT OR IGNORE INTO review_queue(
                    id,entity,proposed_change,current_value,proposed_value,sources,evidence,
                    confidence,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (review_id, f"benchmark_result:{previous['id']}", "publisher_score_correction",
                     str(previous["score"]), str(score), json.dumps([record["source_url"]]),
                     json.dumps(evidence, sort_keys=True), "MEDIUM",
                     "Publisher changed a score for an existing run; previous result retained.",
                     record["evaluated_at"]))
            continue
        values["score"] = score
        columns = ",".join(keys)
        placeholders = ",".join("?" for _ in keys)
        db.execute(f"INSERT INTO benchmark_results({columns}) VALUES({placeholders})",
                   [values.get(key) for key in keys])
        inserted += 1
    return inserted

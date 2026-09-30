"""Strict adapter for publisher-backed structured benchmark exports.

The adapter intentionally does not fetch or scrape publisher pages. Callers must
provide a reproducible structured export and its source URL. Missing run metadata
is retained as SQL NULL rather than inferred.
"""

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
    """Insert exact-version rows from a structured publisher/export record list."""
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
        keys = ("benchmark_id", "model_id", "offering_id", "model_version", "score", "metric",
                "harness_name", "harness_version", "scaffold", "reasoning_setting", "task_subset",
                "tool_policy", "network_policy", "step_budget", "token_budget", "time_budget_seconds",
                "attempts_per_task", "grader_version", "confidence_interval", "evaluated_at", "source_id",
                "confidence", "input_tokens", "cached_input_tokens", "cache_write_tokens", "answer_tokens",
                "reasoning_tokens", "total_output_tokens", "model_cost_usd", "infrastructure_cost_usd",
                "cost_per_task_usd", "wall_time_seconds", "pricing_snapshot_at", "telemetry_complete")
        values = {**record, "benchmark_id": benchmark[0], "source_id": source_id}
        columns = ",".join(keys)
        placeholders = ",".join("?" for _ in keys)
        db.execute(f"INSERT INTO benchmark_results({columns}) VALUES({placeholders})",
                   [values.get(key) for key in keys])
        inserted += 1
    return inserted

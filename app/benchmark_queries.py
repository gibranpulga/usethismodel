"""Grouping helpers for benchmark comparisons that are genuinely comparable."""

COMPARABILITY_FIELDS = (
    "benchmark_id", "benchmark", "name", "version", "metric", "task_subset",
    "harness_name", "harness_version", "scaffold", "reasoning_setting",
    "tool_policy", "network_policy", "step_budget", "token_budget",
    "time_budget_seconds", "attempts_per_task", "grader_version",
)


def comparison_key(row):
    """Return only the published dimensions needed for a like-for-like run."""
    row = dict(row)
    return tuple(row.get(field) for field in COMPARABILITY_FIELDS)


def comparable_groups(rows, minimum_models=2):
    groups = {}
    for row in rows:
        groups.setdefault(comparison_key(row), []).append(dict(row))
    result = []
    for key, entries in groups.items():
        # A shared NULL configuration is unknown evidence, not proof that two
        # evaluations used the same scaffold or settings.
        first = entries[0]
        if not first.get("task_subset") or not (first.get("harness_name") or first.get("scaffold")):
            continue
        model_ids = {entry.get("model_id") for entry in entries if entry.get("model_id") is not None}
        if len(model_ids) < minimum_models:
            continue
        config = [first.get(field) for field in (
            "task_subset", "harness_name", "harness_version", "scaffold", "reasoning_setting",
            "tool_policy", "network_policy", "attempts_per_task", "grader_version")]
        result.append({
            "benchmark": first.get("benchmark") or first.get("name"),
            "version": first.get("version"),
            "metric": first.get("metric"),
            "configuration": {name: value for name, value in zip(
                ("task_subset", "harness", "harness_version", "scaffold", "reasoning_setting",
                 "tool_policy", "network_policy", "attempts_per_task", "grader_version"), config)
                if value is not None},
            "results": sorted(entries, key=lambda entry: (entry.get("model") or entry.get("canonical_name") or "").casefold()),
        })
    return result

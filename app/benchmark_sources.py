"""Curated, score-free metadata for benchmark publishers.

This module deliberately tracks benchmark identity and methodology only.  Result
scores belong in ``benchmark_results`` and must be supported separately.
"""

import csv
import hashlib
import io
import json
import re
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class BenchmarkSource:
    name: str
    version: str
    category: str
    description: str
    publisher: str
    source_url: str
    methodology_url: str
    published_at: str | None
    task_count: int | None


# Verified against the linked publisher pages on 2026-09-29. Keep superseded
# database rows: a version change should add a row, not rewrite the old version.
BENCHMARK_REGISTRY = (
    BenchmarkSource(
        name="Artificial Analysis Intelligence Index",
        version="4.3.2",
        category="General/Reasoning/Coding/Agents",
        description="Composite index of ten independently run evaluations.",
        publisher="Artificial Analysis",
        source_url=(
            "https://artificialanalysis.ai/evaluations/"
            "artificial-analysis-intelligence-index"
        ),
        methodology_url=(
            "https://artificialanalysis.ai/methodology/intelligence-benchmarking"
        ),
        published_at="2026-09-07",
        task_count=9750,
    ),
    BenchmarkSource(
        name="Artificial Analysis Coding Agent Index",
        version="1.5",
        category="Coding agent",
        description=(
            "Equal-weight index of DeepSWE v1.1, Terminal-Bench 4.0, "
            "and SWE-Atlas-QnA."
        ),
        publisher="Artificial Analysis",
        source_url="https://artificialanalysis.ai/agents/coding-agents",
        methodology_url=(
            "https://artificialanalysis.ai/methodology/coding-agents-benchmarking/"
        ),
        published_at="2026-09",
        task_count=303,
    ),
    BenchmarkSource(
        name="Terminal-Bench",
        version="4.0.0",
        category="Agentic terminal use",
        description="Terminal-based tasks with test-suite pass/fail verification.",
        publisher="Harbor / Terminal-Bench",
        source_url="https://www.tbench.ai/news/terminal-bench-4-0",
        methodology_url=(
            "https://github.com/harbor-framework/terminal-bench/releases/tag/v4.0.0"
        ),
        published_at="2026-08-26",
        task_count=66,
    ),
    BenchmarkSource(
        name="LiveBench",
        version="2026-06-25",
        category="General/Reasoning/Coding/Agents",
        description="Contamination-aware benchmark spanning seven capability categories.",
        publisher="LiveBench",
        source_url="https://livebench.ai/",
        methodology_url="https://livebench.ai/livebench.pdf",
        published_at="2026-06-25",
        task_count=23,
    ),
    BenchmarkSource(
        name="SWE-bench Verified",
        version="500-task subset",
        category="Coding agent",
        description="Human-validated subset of SWE-bench software-engineering tasks.",
        publisher="SWE-bench",
        source_url="https://www.swebench.com/verified.html",
        methodology_url="https://openai.com/index/introducing-swe-bench-verified/",
        published_at="2024-08-13",
        task_count=500,
    ),
    BenchmarkSource(
        name="SWE-bench Pro",
        version="V2",
        category="Coding agent",
        description="Validated public split with a locked evaluation protocol.",
        publisher="Scale AI",
        source_url="https://labs.scale.com/leaderboard/swe_bench_pro_public_v2",
        methodology_url=(
            "https://github.com/scaleapi/SWE-bench_Pro-os/blob/main/v2/README.md"
        ),
        published_at="2026-09-22",
        task_count=642,
    ),
)


def _timestamp(value: str | date | datetime) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if not isinstance(value, str) or not value.strip():
        raise ValueError("now must be a non-empty ISO timestamp or date/datetime")
    return value


def sync_benchmark_registry(db, now: str | date | datetime) -> int:
    """Synchronize current metadata while retaining every superseded version.

    The benchmark freshness migration is expected to have added ``is_current``,
    ``last_verified_at``, ``published_at``, ``methodology_url``, and
    ``task_count`` to ``benchmarks``.
    """

    verified_at = _timestamp(now)
    for benchmark in BENCHMARK_REGISTRY:
        db.execute(
            """INSERT INTO sources(name,url,source_type,fetched_at,reliability)
               VALUES(?,?,?,?,?)
               ON CONFLICT(url) DO UPDATE SET
                 name=excluded.name,
                 source_type=excluded.source_type,
                 fetched_at=excluded.fetched_at,
                 reliability=excluded.reliability""",
            (benchmark.publisher, benchmark.source_url, "benchmark_publisher", verified_at, "HIGH"),
        )
        source_id = db.execute(
            "SELECT id FROM sources WHERE url=?", (benchmark.source_url,)
        ).fetchone()[0]

        # Only retire other versions of this benchmark. Unrelated catalogue
        # entries remain outside this deliberately bounded registry's scope.
        db.execute(
            "UPDATE benchmarks SET is_current=0 WHERE name=? AND version<>?",
            (benchmark.name, benchmark.version),
        )
        db.execute(
            """INSERT INTO benchmarks(
                 name,version,category,description,source_id,is_current,
                 last_verified_at,published_at,methodology_url,task_count
               ) VALUES(?,?,?,?,?,1,NULL,?,?,?)
               ON CONFLICT(name,version) DO UPDATE SET
                 category=excluded.category,description=excluded.description,
                 source_id=excluded.source_id,is_current=1,
                 published_at=excluded.published_at,
                 methodology_url=excluded.methodology_url,task_count=excluded.task_count""",
            (
                benchmark.name, benchmark.version, benchmark.category,
                benchmark.description, source_id, benchmark.published_at,
                benchmark.methodology_url, benchmark.task_count,
            ),
        )

    return len(BENCHMARK_REGISTRY)


LIVEBENCH_CSV = (
    "https://raw.githubusercontent.com/LiveBench/new-livebench/main/public/"
    "table_2026_06_25.csv"
)
SWE_BENCH_VERIFIED_JSON = (
    "https://raw.githubusercontent.com/swe-bench/swe-bench.github.io/"
    "master/data/leaderboards.json"
)
TERMINAL_SUBMISSIONS_API = (
    "https://api.github.com/repos/harbor-framework/terminal-bench/"
    "contents/leaderboard/submissions"
)


def _read_url(url: str, accept: str | None = None) -> bytes:
    headers = {"User-Agent": "UseThisModel-benchmark-import/1.0"}
    if accept:
        headers["Accept"] = accept
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=45) as response:
        return response.read()


def _json(url: str):
    return json.loads(_read_url(url, "application/vnd.github+json"))


def _review(db, source: str, now: str, reason: str, evidence=None) -> None:
    payload = {"source": source, "reason": reason, "evidence": evidence}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24]
    db.execute("""INSERT OR IGNORE INTO review_queue(
        id,entity,proposed_change,current_value,proposed_value,sources,evidence,
        confidence,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (digest, f"benchmark_source:{source}", "review_publisher_data", None, None,
         json.dumps([source]), json.dumps(payload, sort_keys=True, default=str), "LOW", reason, now))


def _model_maps(db):
    exact = {}
    for row in db.execute("SELECT id,canonical_slug FROM models WHERE canonical_slug IS NOT NULL"):
        exact.setdefault(row["canonical_slug"].casefold(), set()).add(row["id"])
    for row in db.execute("SELECT model_id,alias FROM model_aliases"):
        exact.setdefault(row["alias"].casefold(), set()).add(row["model_id"])
    routes = {}
    for row in db.execute("SELECT model_id,api_model_id FROM provider_offerings"):
        routes.setdefault(row["api_model_id"].casefold(), set()).add(row["model_id"])
    return exact, routes


def _resolve_model(identity: str, exact, routes):
    route_candidates = routes.get(identity.casefold())
    if route_candidates is not None:
        return next(iter(route_candidates)) if len(route_candidates) == 1 else None
    candidates = exact.get(identity.casefold(), set())
    return next(iter(candidates)) if len(candidates) == 1 else None


def _register_source(db, name, url, now):
    db.execute("""INSERT INTO sources(name,url,source_type,fetched_at,reliability)
        VALUES(?,?, 'benchmark_publisher', ?, 'HIGH') ON CONFLICT(url) DO UPDATE SET
        name=excluded.name,source_type=excluded.source_type,fetched_at=excluded.fetched_at,
        reliability=excluded.reliability""", (name, url, now))


def _livebench_records(db, now):
    raw = _read_url(LIVEBENCH_CSV).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or "model" not in reader.fieldnames:
        raise ValueError("LiveBench export schema changed: missing model column")
    metric_columns = [column for column in reader.fieldnames if column != "model"]
    if not metric_columns:
        raise ValueError("LiveBench export schema changed: no task score columns")
    version = next(item.version for item in BENCHMARK_REGISTRY if item.name == "LiveBench")
    exact, routes = _model_maps(db)
    records = []
    unmatched = []
    for row in reader:
        if not row.get("model"):
            raise ValueError("LiveBench export schema changed: row has no model identity")
        model_id = _resolve_model(row["model"], exact, routes)
        if model_id is None:
            unmatched.append(row["model"])
            continue
        for task in metric_columns:
            raw_score = row.get(task, "").strip()
            if not raw_score:
                continue
            records.append({
                "benchmark_name": "LiveBench", "benchmark_version": version,
                "model_id": model_id, "score": float(raw_score), "metric": "accuracy (%)",
                "task_subset": task, "source_url": LIVEBENCH_CSV,
                "evaluated_at": "2026-06-25", "confidence": "MEDIUM",
            })
    return records, unmatched


def _terminal_records(db):
    entries = _json(TERMINAL_SUBMISSIONS_API)
    if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
        raise ValueError("Terminal-Bench submission listing schema changed")
    exact, routes = _model_maps(db)
    records, unmatched = [], []
    version = next(item.version for item in BENCHMARK_REGISTRY if item.name == "Terminal-Bench")
    for entry in entries:
        if not entry.get("name", "").endswith(".json"):
            continue
        url = entry.get("download_url")
        if not url:
            raise ValueError("Terminal-Bench listing has a JSON entry without download_url")
        payload = _json(url)
        meta = payload.get("metadata")
        metrics = payload.get("metrics")
        source_filter = payload.get("source_filter")
        if not all(isinstance(part, dict) for part in (meta, metrics, source_filter)):
            raise ValueError("Terminal-Bench submission schema changed")
        identity = source_filter.get("model_name")
        model_id = _resolve_model(identity, exact, routes) if isinstance(identity, str) else None
        if model_id is None:
            unmatched.append(identity or entry["name"])
            continue
        if not isinstance(metrics.get("accuracy"), (int, float)) or not meta.get("date"):
            raise ValueError("Terminal-Bench submission is missing accuracy or evaluation date")
        records.append({
            "benchmark_name": "Terminal-Bench", "benchmark_version": version,
            "model_id": model_id, "model_version": identity, "score": metrics["accuracy"],
            "metric": "accuracy (%)", "harness_name": meta.get("agent_display", {}).get("label"),
            "harness_version": source_filter.get("agent_version"),
            "scaffold": source_filter.get("agent"),
            "reasoning_setting": meta.get("reasoning_effort"),
            "task_subset": "terminal-bench/terminal-bench@v4.0.0",
            "attempts_per_task": payload.get("n_attempts"),
            "confidence_interval": (str(metrics["accuracy_ci95_half_width"]) + " percentage points (95% CI)")
                if metrics.get("accuracy_ci95_half_width") is not None else None,
            "evaluated_at": meta["date"], "source_url": url, "confidence": "HIGH",
        })
    return records, unmatched


def _swe_verified_records(db):
    payload = _json(SWE_BENCH_VERIFIED_JSON)
    boards = payload.get("leaderboards") if isinstance(payload, dict) else None
    if not isinstance(boards, list):
        raise ValueError("SWE-bench leaderboard schema changed")
    verified = next((board for board in boards if board.get("name") == "Verified"), None)
    if not verified or not isinstance(verified.get("results"), list):
        raise ValueError("SWE-bench Verified results are missing")
    exact, routes = _model_maps(db)
    records, unmatched = [], []
    for row in verified["results"]:
        if not isinstance(row.get("date"), str) or row["date"] < "2026-01-01":
            continue
        model_ids = [tag[7:] for tag in row.get("tags", []) if isinstance(tag, str) and tag.startswith("Model: ")]
        resolved = {_resolve_model(identity, exact, routes) for identity in model_ids}
        resolved.discard(None)
        if len(resolved) != 1 or not model_ids:
            unmatched.append(row.get("name", "unnamed result"))
            continue
        if not isinstance(row.get("resolved"), (int, float)):
            raise ValueError("SWE-bench Verified row is missing resolved score")
        agent = row.get("agent")
        attempts = next((int(m.group(1)) for tag in row.get("tags", [])
                         if isinstance(tag, str) and (m := re.search(r"System: Attempts - (\d+)", tag))), None)
        records.append({
            "benchmark_name": "SWE-bench Verified", "benchmark_version": "500-task subset",
            "model_id": next(iter(resolved)), "model_version": model_ids[0],
            "score": row["resolved"], "metric": "resolved (%)", "harness_name": agent,
            "scaffold": agent, "reasoning_setting": row.get("reasoning_effort"),
            "task_subset": "Verified (500 tasks)", "attempts_per_task": attempts,
            "evaluated_at": row["date"], "source_url": SWE_BENCH_VERIFIED_JSON,
            "confidence": "HIGH" if row.get("checked") is True else "MEDIUM",
        })
    return records, unmatched


def sync_publisher_results(db, now: str | date | datetime) -> dict:
    """Import stable publisher exports; failures leave accepted scores untouched."""
    from .benchmark_import import import_publisher_results

    timestamp = _timestamp(now)
    sources = (
        ("LiveBench", lambda: _livebench_records(db, timestamp)),
        ("Terminal-Bench", lambda: _terminal_records(db)),
        ("SWE-bench", lambda: _swe_verified_records(db)),
    )
    result = {"inserted": 0, "unmatched_models": {}, "failures": []}
    for index, (source, fetch_records) in enumerate(sources):
        savepoint = f"benchmark_source_{index}"
        db.execute(f"SAVEPOINT {savepoint}")
        try:
            records, unmatched = fetch_records()
            if source == "LiveBench":
                _register_source(db, "LiveBench publisher dataset", LIVEBENCH_CSV, timestamp)
            elif source == "SWE-bench":
                _register_source(db, "SWE-bench official leaderboard data", SWE_BENCH_VERIFIED_JSON, timestamp)
            # Terminal result rows each carry a distinct submission source URL.
            for url in {record["source_url"] for record in records}:
                _register_source(db, "Terminal-Bench official submission", url, timestamp)
            inserted = import_publisher_results(db, records)
            registry_name = {"SWE-bench": "SWE-bench Verified"}.get(source, source)
            registry_version = "500-task subset" if source == "SWE-bench" else next(
                item.version for item in BENCHMARK_REGISTRY if item.name == registry_name)
            db.execute("UPDATE benchmarks SET last_verified_at=? WHERE name=? AND version=?",
                       (timestamp, registry_name, registry_version))
            if unmatched:
                _review(db, source, timestamp,
                        "Some publisher model IDs do not resolve uniquely; their scores were not imported.", unmatched)
            db.execute(f"RELEASE SAVEPOINT {savepoint}")
            result["inserted"] += inserted
            result["unmatched_models"][source] = unmatched
        except Exception as error:
            db.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            db.execute(f"RELEASE SAVEPOINT {savepoint}")
            message = f"{type(error).__name__}: {error}"
            result["failures"].append({"source": source, "error": message})
            _review(db, source, timestamp, "Publisher data import failed; previous known-valid scores retained.", message)
    return result

"""Curated, score-free metadata for benchmark publishers.

This module deliberately tracks benchmark identity and methodology only.  Result
scores belong in ``benchmark_results`` and must be supported separately.
"""

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
               ) VALUES(?,?,?,?,?,1,?,?,?,?)
               ON CONFLICT(name,version) DO UPDATE SET
                 category=excluded.category,description=excluded.description,
                 source_id=excluded.source_id,is_current=1,
                 last_verified_at=excluded.last_verified_at,
                 published_at=excluded.published_at,
                 methodology_url=excluded.methodology_url,task_count=excluded.task_count""",
            (
                benchmark.name, benchmark.version, benchmark.category,
                benchmark.description, source_id, verified_at,
                benchmark.published_at, benchmark.methodology_url, benchmark.task_count,
            ),
        )

    return len(BENCHMARK_REGISTRY)

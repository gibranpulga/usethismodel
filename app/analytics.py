"""Anonymous aggregate counters for public product usage."""

from __future__ import annotations

from datetime import date

ALLOWED_EVENTS = {
    "search", "model_view", "harness_view", "filters", "comparison",
    "deal_click", "api_request", "mcp_request",
}


def record(db, event: str, dimension: str = "") -> None:
    """Increment a bounded aggregate; deliberately accepts no visitor data."""
    if event not in ALLOWED_EVENTS:
        return
    safe_dimension = str(dimension or "")[:160]
    db.execute(
        """INSERT INTO analytics_daily(day,event,dimension,count) VALUES(?,?,?,1)
           ON CONFLICT(day,event,dimension) DO UPDATE SET count=count+1""",
        (date.today().isoformat(), event, safe_dimension),
    )
    db.commit()


"""Exact, unit-aware PAYG estimates from recorded current price classes."""

TOKEN_UNITS = {"per_1m_tokens", "per_million_tokens"}


def estimate_token_cost(prices, usage, batch=False):
    """Return an estimate only when every requested class has an exact price."""
    requested = {"INPUT": usage.get("input", 0), "OUTPUT": usage.get("output", 0),
                 "CACHE_READ": usage.get("cache_read", 0), "CACHE_WRITE": usage.get("cache_write", 0)}
    if batch:
        for base, amount in (("INPUT", requested["INPUT"]), ("OUTPUT", requested["OUTPUT"])):
            if amount and prices.get("BATCH_" + base) is not None:
                requested[base] = 0
                requested["BATCH_" + base] = amount
    cost = 0.0
    missing = []
    for kind, amount in requested.items():
        if not amount:
            continue
        record = prices.get(kind)
        if record is None:
            missing.append(kind)
            continue
        if record.get("unit", "per_1m_tokens") not in TOKEN_UNITS:
            missing.append(kind + " (incompatible unit)")
            continue
        if record.get("tiered"):
            missing.append(kind + " (context tier unspecified)")
            continue
        cost += float(record["amount"]) * amount / 1_000_000
    return {"cost": cost if not missing else None, "missing": missing,
            "batch_classes_used": [k for k in requested if k.startswith("BATCH_") and requested[k]]}

"""Small, explainable catalogue rules.  Facts live in SQLite; this is not a matrix."""

import re

UNKNOWN = "UNKNOWN"
COMPATIBILITY = {
    "COMPATIBLE",
    "COMPATIBLE_WITH_CONFIGURATION",
    "PARTIAL",
    "NOT_COMPATIBLE",
    "UNKNOWN",
}


def normalize_model_id(value: str) -> str:
    """Normalize a provider id without throwing away provider-specific aliases."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def canonical_model(db, provider_id: int | None, api_model_id: str):
    """Resolve an alias first, then an exact canonical slug; never guess silently."""
    normalized = normalize_model_id(api_model_id)
    row = db.execute(
        """SELECT m.* FROM model_aliases a JOIN models m ON m.id=a.model_id
           WHERE lower(a.alias)=? AND (a.provider_id=? OR a.provider_id IS NULL)
           ORDER BY a.provider_id IS NOT NULL DESC LIMIT 1""",
        (api_model_id.lower(), provider_id),
    ).fetchone()
    if row:
        return row
    return db.execute(
        "SELECT * FROM models WHERE replace(lower(canonical_slug), '_', '-')=?",
        (normalized,),
    ).fetchone()


def compatibility_for(db, harness_id: int, offering_id: int, mcp_workflow: bool = False):
    offering = db.execute(
        """SELECT o.*, p.name provider_name, m.canonical_name
           FROM provider_offerings o JOIN providers p ON p.id=o.provider_id
           JOIN models m ON m.id=o.model_id WHERE o.id=?""",
        (offering_id,),
    ).fetchone()
    harness = db.execute("SELECT * FROM harnesses WHERE id=?", (harness_id,)).fetchone()
    if not offering or not harness:
        return {
            "status": UNKNOWN,
            "confidence": "LOW",
            "explanation": "Harness or provider offering was not found.",
        }

    override = db.execute(
        """SELECT * FROM harness_model_overrides WHERE harness_id=?
           AND (offering_id=? OR model_id=?) ORDER BY offering_id IS NOT NULL DESC LIMIT 1""",
        (harness_id, offering_id, offering["model_id"]),
    ).fetchone()
    if override:
        return {
            "status": override["status"],
            "confidence": "HIGH",
            "explanation": override["reason"],
        }
    provider = db.execute(
        "SELECT * FROM harness_provider_compatibility WHERE harness_id=? AND provider_id=?",
        (harness_id, offering["provider_id"]),
    ).fetchone()
    mode = provider["support_mode"] if provider else UNKNOWN
    if mode == "NO":
        return {
            "status": "NOT_COMPATIBLE",
            "confidence": "HIGH",
            "explanation": f"{harness['name']} documents no support for {offering['provider_name']}.",
        }
    if mode == UNKNOWN:
        return {
            "status": UNKNOWN,
            "confidence": "LOW",
            "explanation": f"No documented {harness['name']} route for {offering['provider_name']}.",
        }
    if offering["tool_support"] == "NO":
        return {
            "status": "PARTIAL",
            "confidence": "HIGH",
            "explanation": "The provider route exists, but this offering does not expose tool calling.",
        }
    mcp = "YES" if harness["supports_mcp"] else "NO" if harness["supports_mcp"] == 0 else UNKNOWN
    if mcp_workflow and mcp != "YES":
        return {
            "status": "NOT_COMPATIBLE" if mcp == "NO" else UNKNOWN,
            "confidence": "MEDIUM",
            "explanation": "The workflow requires MCP but harness MCP support is not documented as available.",
        }
    if offering["tool_support"] == UNKNOWN:
        return {
            "status": "PARTIAL",
            "confidence": "MEDIUM",
            "explanation": "Provider integration is documented, but tool support for this route is unknown.",
        }
    configured = mode in {"CONFIGURATION", "OPENAI_COMPATIBLE", "OPENROUTER"}
    status = "COMPATIBLE_WITH_CONFIGURATION" if configured else "COMPATIBLE"
    bits = [f"Provider support: {mode.replace('_', ' ').title()}", "Tool calling: Yes"]
    if mcp_workflow:
        bits.append("Harness MCP: Yes")
    return {"status": status, "confidence": "HIGH", "explanation": ". ".join(bits) + "."}

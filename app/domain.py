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
    return next(
        (row for row in db.execute("SELECT * FROM models WHERE canonical_slug IS NOT NULL")
         if normalize_model_id(row["canonical_slug"]) == normalized),
        None,
    )


def compatibility_for(
    db,
    harness_id: int,
    offering_id: int,
    mcp_workflow: bool = False,
    workflow_id: int | None = None,
):
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

    workflow_check = None
    if workflow_id is not None:
        workflow_rows = db.execute(
            """SELECT whc.state,whc.reason,wi.name integration_name
               FROM workflow_harness_compatibility whc
               JOIN workflow_integrations wi ON wi.id=whc.integration_id
               WHERE whc.harness_id=? AND wi.workflow_id=?
               ORDER BY CASE whc.state WHEN 'YES' THEN 0 WHEN 'CONFIGURATION' THEN 1
                         WHEN 'PARTIAL' THEN 2 WHEN 'UNKNOWN' THEN 3 ELSE 4 END""",
            (harness_id, workflow_id),
        ).fetchall()
        if workflow_rows:
            workflow_check = {
                "state": workflow_rows[0]["state"],
                "reason": workflow_rows[0]["reason"],
                "integrations": [row["integration_name"] for row in workflow_rows],
            }
        else:
            workflow_check = {
                "state": UNKNOWN,
                "reason": "No source-backed host result is recorded for this workflow and harness.",
                "integrations": [],
            }

    evidence = db.execute(
        """SELECT rce.*,s.name source_name,s.url source_url
           FROM route_compatibility_evidence rce JOIN sources s ON s.id=rce.source_id
           WHERE rce.harness_id=? AND rce.offering_id=?
           ORDER BY CASE rce.capability WHEN 'MCP_TOOLS' THEN 0 ELSE 1 END LIMIT 1""",
        (harness_id, offering_id),
    ).fetchone()
    if evidence:
        status = evidence["mcp_workflow_status"]
        if workflow_check and workflow_check["state"] == "NO":
            status = "NOT_COMPATIBLE"
        elif workflow_check and workflow_check["state"] == UNKNOWN:
            status = UNKNOWN
        explanation = f"Tool calling: {evidence['provider_tool_calls'].title()}. " + evidence["reason"]
        if workflow_check:
            explanation += " Workflow host: " + workflow_check["reason"]
        return {
            "status": status,
            "confidence": "HIGH",
            "explanation": explanation,
            "access_method": evidence["access_method"],
            "checks": {
                "harness_can_use_model": evidence["harness_can_use_model"],
                "harness_supports_mcp": evidence["harness_supports_mcp"],
                "provider_route_tool_calls": evidence["provider_tool_calls"],
                "tool_call_reliability": evidence["tool_reliability"],
                "workflow_host": workflow_check["state"] if workflow_check else None,
            },
            "source": {"name": evidence["source_name"], "url": evidence["source_url"]},
            "verified_at": evidence["verified_at"],
        }

    override = db.execute(
        """SELECT * FROM harness_model_overrides WHERE harness_id=?
           AND (offering_id=? OR (offering_id IS NULL AND model_id=?))
           ORDER BY offering_id IS NOT NULL DESC LIMIT 1""",
        (harness_id, offering_id, offering["model_id"]),
    ).fetchone()
    # An explicit model/route result is authoritative for ordinary compatibility,
    # but cannot manufacture MCP support in a harness that lacks it.
    if override and not mcp_workflow:
        return {"status": override["status"], "confidence": "HIGH", "explanation": override["reason"]}
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
    if workflow_check and workflow_check["state"] in {"NO", UNKNOWN}:
        return {
            "status": "NOT_COMPATIBLE" if workflow_check["state"] == "NO" else UNKNOWN,
            "confidence": "MEDIUM",
            "explanation": workflow_check["reason"],
            "checks": {
                "harness_can_use_model": "YES" if mode != UNKNOWN else UNKNOWN,
                "harness_supports_mcp": mcp,
                "provider_route_tool_calls": offering["tool_support"],
                "tool_call_reliability": "UNKNOWN",
                "workflow_host": workflow_check["state"],
            },
        }
    if mcp_workflow and mcp != "YES":
        return {
            "status": "NOT_COMPATIBLE" if mcp == "NO" else UNKNOWN,
            "confidence": "MEDIUM",
            "explanation": "The workflow requires MCP but harness MCP support is not documented as available.",
        }
    if override:
        return {"status": override["status"], "confidence": "HIGH", "explanation": override["reason"]}
    if offering["tool_support"] == UNKNOWN:
        return {
            "status": "PARTIAL",
            "confidence": "MEDIUM",
            "explanation": "Provider integration is documented, but tool support for this route is unknown.",
        }
    configured = mode in {"CONFIGURATION", "OPENAI_COMPATIBLE", "OPENROUTER"}
    status = "COMPATIBLE_WITH_CONFIGURATION" if configured else "COMPATIBLE"
    access_method = {
        "OPENROUTER": "OpenRouter API key",
        "OPENAI_COMPATIBLE": "custom OpenAI-compatible endpoint",
        "CONFIGURATION": "provider API key and harness configuration",
        "NATIVE": "native provider login or API key (route dependent)",
    }.get(mode, "documented provider integration")
    bits = [f"Provider support: {mode.replace('_', ' ').title()}", "Tool calling: Yes"]
    if mcp_workflow:
        bits.append("Harness MCP: Yes")
    if workflow_check:
        bits.append(f"Workflow host: {workflow_check['state'].replace('_', ' ').title()}")
    return {
        "status": status,
        "confidence": "MEDIUM",
        "explanation": ". ".join(bits) + ". No route-specific reliability test is recorded.",
        "access_method": access_method,
        "checks": {
            "harness_can_use_model": "YES",
            "harness_supports_mcp": mcp,
            "provider_route_tool_calls": offering["tool_support"],
            "tool_call_reliability": "UNKNOWN",
            "workflow_host": workflow_check["state"] if workflow_check else None,
        },
    }

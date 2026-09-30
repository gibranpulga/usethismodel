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
        """SELECT o.*, p.name provider_name, m.canonical_name,
                  (SELECT name FROM sources WHERE id=o.source_id) route_source_name,
                  (SELECT url FROM sources WHERE id=o.source_id) route_source_url
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
            """SELECT whc.state,whc.reason,whc.verified_at,wi.name integration_name,
                      s.name source_name,s.url source_url
               FROM workflow_harness_compatibility whc
               JOIN workflow_integrations wi ON wi.id=whc.integration_id
               LEFT JOIN sources s ON s.id=whc.source_id
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
                "verified_at": max(row["verified_at"] for row in workflow_rows),
                "sources": list({(row["source_name"], row["source_url"]):
                                 {"name": row["source_name"], "url": row["source_url"]}
                                 for row in workflow_rows if row["source_url"]}.values()),
            }
        else:
            workflow_check = {
                "state": UNKNOWN,
                "reason": "No source-backed host result is recorded for this workflow and harness.",
                "integrations": [],
                "verified_at": None,
                "sources": [],
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
            "derived": False,
            "evidence_kind": "EXPLICIT_ROUTE_EVIDENCE",
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
            "sources": [
                {"name": evidence["source_name"], "url": evidence["source_url"]},
                *(workflow_check["sources"] if workflow_check else []),
            ],
            "workflow_evidence": workflow_check,
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
        return {"status": override["status"], "confidence": "HIGH", "derived": False,
                "evidence_kind": "EXPLICIT_MODEL_OR_ROUTE_OVERRIDE", "explanation": override["reason"]}
    # OpenRouter is a documented, explicit harness integration. An exact route
    # on OpenRouter can be derived for harnesses whose official access-method
    # record says they support it; this never generalizes to other providers.
    if offering["provider_name"].lower() == "openrouter":
        access = db.execute(
            """SELECT ha.*,s.name source_name,s.url source_url FROM harness_access_methods ha
               JOIN sources s ON s.id=ha.source_id
               WHERE ha.harness_id=? AND ha.access_method='OPENROUTER' AND ha.state='YES'""",
            (harness_id,),
        ).fetchone()
        model_is_claude = "claude" in (offering["canonical_name"] or "").lower()
        if access and (harness["name"] != "Claude Code" or model_is_claude):
            mcp = "YES" if harness["supports_mcp"] else "NO" if harness["supports_mcp"] == 0 else UNKNOWN
            if workflow_check and workflow_check["state"] in {"NO", UNKNOWN}:
                derived_status = "NOT_COMPATIBLE" if workflow_check["state"] == "NO" else UNKNOWN
            elif mcp_workflow and mcp != "YES":
                derived_status = "NOT_COMPATIBLE" if mcp == "NO" else UNKNOWN
            elif offering["tool_support"] == "NO":
                derived_status = "PARTIAL"
            elif offering["tool_support"] == UNKNOWN:
                derived_status = "PARTIAL"
            else:
                derived_status = "COMPATIBLE_WITH_CONFIGURATION"
            return {
                "status": derived_status,
                "confidence": "MEDIUM",
                "derived": True,
                "evidence_kind": "DERIVED_OPENROUTER_ACCESS",
                "explanation": (
                    f"Harness capability: documented OpenRouter access ({access['note'] or access['access_method']}). "
                    "Provider interface: OpenRouter route using an OpenRouter API key. "
                    f"Model tool support: {offering['tool_support']}. MCP required: {'yes' if mcp_workflow else 'no'}; "
                    "configuration: required. Route reliability is unknown."
                    + (f" Workflow host: {workflow_check['reason']}" if workflow_check else "")
                ),
                "access_method": "OpenRouter API key",
                "checks": {
                    "harness_can_use_model": "YES",
                    "harness_supports_mcp": mcp,
                    "provider_route_tool_calls": offering["tool_support"],
                    "tool_call_reliability": UNKNOWN,
                    "workflow_host": workflow_check["state"] if workflow_check else None,
                },
                "source": {"name": access["source_name"], "url": access["source_url"]},
                "sources": [source for source in [
                    {"name": access["source_name"], "url": access["source_url"]},
                    {"name": offering["route_source_name"], "url": offering["route_source_url"]},
                    *(workflow_check["sources"] if workflow_check else []),
                ] if source["url"]],
                "workflow_evidence": workflow_check,
                "verified_at": access["verified_at"],
                "provider_verified_at": offering["last_verified_at"],
            }
    # A direct-provider route can be derived only from a matching, affirmative
    # protocol fact on both sides. Provider branding alone is never consulted.
    protocol = db.execute(
        """SELECT ppe.protocol,ppe.note provider_note,ppe.verified_at provider_verified_at,
                  ps.name provider_source_name,ps.url provider_source_url,
                  hps.access_method,hps.note harness_note,hps.verified_at harness_verified_at,
                  hs.name harness_source_name,hs.url harness_source_url
           FROM provider_protocol_evidence ppe
           JOIN harness_protocol_support hps ON hps.protocol=ppe.protocol
           JOIN sources ps ON ps.id=ppe.source_id
           JOIN sources hs ON hs.id=hps.source_id
           WHERE ppe.provider_id=? AND hps.harness_id=?
             AND ppe.state='YES' AND hps.state='YES'
           ORDER BY CASE hps.access_method WHEN 'NATIVE_PROVIDER' THEN 0 ELSE 1 END,
                    ppe.protocol LIMIT 1""",
        (offering["provider_id"], harness_id),
    ).fetchone()
    claude_code_model_allowed = (
        harness["name"] != "Claude Code"
        or "claude" in (offering["canonical_name"] or "").lower()
    )
    if protocol and claude_code_model_allowed:
        if workflow_check and workflow_check["state"] == "NO":
            derived_status = "NOT_COMPATIBLE"
        elif workflow_check and workflow_check["state"] == UNKNOWN:
            derived_status = UNKNOWN
        elif mcp_workflow and harness["supports_mcp"] != 1:
            derived_status = "UNKNOWN" if harness["supports_mcp"] is None else "NOT_COMPATIBLE"
        elif offering["tool_support"] == "NO":
            derived_status = "PARTIAL"
        elif offering["tool_support"] == UNKNOWN:
            derived_status = "PARTIAL"
        else:
            derived_status = (
                "COMPATIBLE_WITH_CONFIGURATION"
                if protocol["access_method"].startswith("CUSTOM_") or workflow_check
                else "COMPATIBLE"
            )
        sources = [
            {"name": protocol["harness_source_name"], "url": protocol["harness_source_url"]},
            {"name": protocol["provider_source_name"], "url": protocol["provider_source_url"]},
            {"name": offering["route_source_name"], "url": offering["route_source_url"]},
            *(workflow_check["sources"] if workflow_check else []),
        ]
        sources = [item for item in sources if item["url"]]
        return {
            "status": derived_status,
            "confidence": "MEDIUM",
            "derived": True,
            "evidence_kind": "DERIVED_PROTOCOL_INTERSECTION",
            "explanation": (
                f"Protocol match: {protocol['protocol']}. {protocol['harness_note']} "
                f"Provider endpoint: {protocol['provider_note']} "
                f"Route tool calling: {offering['tool_support']}. "
                "Exact route reliability is not established by protocol compatibility."
                + (f" Workflow host: {workflow_check['reason']}" if workflow_check else "")
            ),
            "access_method": protocol["access_method"].replace("_", " ").title(),
            "protocol_evidence": {
                "protocol": protocol["protocol"],
                "provider_state": "YES",
                "harness_state": "YES",
                "provider_note": protocol["provider_note"],
                "harness_note": protocol["harness_note"],
                "provider_source_url": protocol["provider_source_url"],
                "harness_source_url": protocol["harness_source_url"],
                "provider_verified_at": protocol["provider_verified_at"],
                "harness_verified_at": protocol["harness_verified_at"],
            },
            "checks": {
                "harness_can_use_model": "YES",
                "harness_supports_mcp": "YES" if harness["supports_mcp"] else UNKNOWN,
                "provider_route_tool_calls": offering["tool_support"],
                "tool_call_reliability": UNKNOWN,
                "workflow_host": workflow_check["state"] if workflow_check else None,
            },
            "source": sources[0],
            "sources": sources,
            "workflow_evidence": workflow_check,
            "verified_at": protocol["harness_verified_at"],
            "provider_verified_at": protocol["provider_verified_at"],
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
    return {
        "status": UNKNOWN,
        "confidence": "LOW",
        "derived": False,
        "evidence_kind": "INCOMPLETE_PROTOCOL_EVIDENCE",
        "explanation": (
            f"{harness['name']} has a provider access record for {offering['provider_name']}, "
            "but no affirmative matching harness protocol and provider endpoint capability "
            "is recorded for this route."
        ),
        "checks": {
            "harness_can_use_model": UNKNOWN,
            "harness_supports_mcp": "YES" if harness["supports_mcp"] else UNKNOWN,
            "provider_route_tool_calls": offering["tool_support"],
            "tool_call_reliability": UNKNOWN,
            "workflow_host": workflow_check["state"] if workflow_check else None,
        },
    }
def compatible_route_rows(db, filters, harness_id, workflow_id=None, require_mcp=False):
    """Qualify routes in SQL-sized pages, then return all evidence-backed matches.

    The filters' public limit and offset are applied by callers after this
    function has selected compatible rows. Candidate pagination is internal,
    deterministic, and has no catalog-size ceiling.
    """
    from .query import route_rows

    page_size = 500
    after_id = 0
    matches = []
    while True:
        candidates = route_rows(
            db,
            {
                **filters,
                "_compatibility_harness_id": harness_id,
                "_after_offering_id": after_id,
                "limit": page_size,
                "offset": 0,
            },
        )
        for row in candidates:
            result = compatibility_for(
                db, harness_id, row["offering_id"], require_mcp, workflow_id
            )
            if result["status"] in {
                "COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION", "PARTIAL"
            }:
                matches.append({**row, "_compatibility": result})
        if len(candidates) < page_size:
            break
        after_id = candidates[-1]["offering_id"]
    matches.sort(key=lambda row: (
        row.get("input_price") is None,
        row.get("input_price") or 0,
        row.get("canonical_name", ""),
        row.get("provider_name", ""),
    ))
    return matches

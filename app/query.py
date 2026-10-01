"""Read-only catalogue queries used by the finder, table, and calculators."""

from __future__ import annotations

import re
from datetime import date, timedelta

MODEL_CATEGORIES = {
    "text": "text LLM",
    "text llm": "text LLM",
    "multimodal": "multimodal LLM",
    "image": "image generation",
    "image generation": "image generation",
    "video": "video generation",
    "video generation": "video generation",
    "speech to text": "speech-to-text",
    "stt": "speech-to-text",
    "text to speech": "text-to-speech",
    "tts": "text-to-speech",
    "audio": "audio/music generation",
    "music": "audio/music generation",
    "embedding": "embedding",
    "reranker": "reranker",
    "3d": "3D generation",
    "3d generation": "3D generation",
}


def modality_category(raw, name=None):
    """Map source modality strings to a small cautious display taxonomy."""
    value = str(raw or "").strip().lower().replace(" ", "")
    if not value:
        return "Other"
    if "3d" in value:
        return "3D generation"
    model_name = str(name or "").casefold()
    if "embedding" in value or "embedding" in model_name:
        return "Embedding"
    if "rerank" in value or "rerank" in model_name:
        return "Reranker"
    if value == "text->audio" or any(word in model_name for word in ("text-to-speech", "tts", "voice generation")):
        return "Text-to-speech"
    if value == "audio->text" or any(word in model_name for word in ("speech-to-text", "stt", "asr", "whisper")):
        return "Speech-to-text"
    if "video generation" in model_name or "text-to-video" in model_name:
        return "Video generation"
    image_generators = ("image generation", "text-to-image", "image generator", "imagen", "ideogram",
                        "dall-e", "gpt-image", "qwen-image", "flux", "recraft", "seedream",
                        "nano banana", "grok imagine image", "muse image")
    if any(marker in model_name for marker in image_generators):
        return "Image generation"
    if value == "audio" and any(word in model_name for word in ("music", "audio generation", "suno", "udio")):
        return "Audio / music"
    if value in {"text", "text->text"}:
        return "Text LLM"
    if "text" in value or any(token in value for token in ("image", "audio", "video", "pdf", "file")):
        return "Multimodal LLM"
    if value in {"audio", "video", "image"}:
        return "Other"
    return "Other"


def normalize_context(value):
    """Normalize positive token counts and common context-window labels."""
    raw = str(value).strip().lower().replace(",", "").replace("_", "")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([km])?\+?", raw)
    if not match:
        raise ValueError("invalid context")
    amount = float(match.group(1))
    amount *= {None: 1, "k": 1_000, "m": 1_000_000}[match.group(2)]
    if amount <= 0 or not amount.is_integer():
        raise ValueError("invalid context")
    return int(amount)


def interpret_search(filters):
    """Translate common finder language into deterministic, shareable facets.

    Explicit controls always win. Remaining words become the ordinary catalogue
    text query; no LLM or opaque relevance score participates.
    """
    result = dict(filters or {})
    raw = str(result.get("q", "")).strip()
    if not raw:
        return result, []
    text = raw.lower()
    applied = []

    def set_if_empty(key, value, label):
        if not result.get(key):
            result[key] = value
            applied.append(label)

    harness_aliases = {
        "claude": "Claude Code", "claude code": "Claude Code", "claude-code": "Claude Code",
        "codex": "Codex CLI", "codex cli": "Codex CLI", "codex-cli": "Codex CLI",
        "opencode": "OpenCode", "open code": "OpenCode",
        "hermes": "Hermes Agent", "hermes agent": "Hermes Agent", "hermes-agent": "Hermes Agent",
        "gemini": "Gemini CLI", "gemini cli": "Gemini CLI", "gemini-cli": "Gemini CLI",
        "qwen": "Qwen Code", "qwen code": "Qwen Code", "qwen-code": "Qwen Code",
        "goose": "Goose", "cline": "Cline", "roo": "Roo Code", "roo code": "Roo Code", "roo-code": "Roo Code",
        "aider": "Aider", "continue": "Continue", "zcode": "ZCode", "zed": "Zed", "pi": "Pi",
        "cursor": "Cursor CLI", "cursor cli": "Cursor CLI", "junie": "Junie CLI", "junie cli": "Junie CLI",
        "amp": "Amp", "droid": "Factory Droid",
    }
    for phrase in sorted(harness_aliases, key=len, reverse=True):
        harness = harness_aliases[phrase]
        pattern = rf"\b(?:works?\s+with\s+)?{re.escape(phrase)}\b"
        if re.search(pattern, text):
            set_if_empty("harness", harness, f"Harness: {harness}")
            text = re.sub(pattern, " ", text)
            break
    if re.search(r"\bfree\b|\$0", text):
        set_if_empty("free", "1", "Price: $0 route")
        text = re.sub(r"\bfree\b|\$0", " ", text)
    if re.search(r"\bincluded\s+with\s+(?:a\s+)?subscription\b|subscription[- ]included", text):
        set_if_empty("included", "1", "Included with subscription")
        text = re.sub(r"included\s+with\s+(?:a\s+)?subscription|subscription[- ]included", " ", text)
    if re.search(r"\btools?\b|tool[ -]?capable|function calling", text):
        set_if_empty("tools", "1", "Tool calling: yes")
        text = re.sub(r"\btools?\b|tool[ -]?capable|function calling", " ", text)
    if re.search(r"\bopenrouter\b", text):
        set_if_empty("access", "openrouter", "Access: OpenRouter")
        text = re.sub(r"\bopenrouter\b", " ", text)
    if re.search(r"\b1m\b|1\s*million", text) and "context" in text:
        set_if_empty("context", "1000000", "Context: 1M+")
        text = re.sub(r"\b1m\b|1\s*million|context", " ", text)
    if re.search(r"open\s+(?:source|weights?)", text):
        set_if_empty("open_weights", "1", "Open weights")
        text = re.sub(r"open\s+(?:source|weights?)", " ", text)
    if "agentic coding" in text:
        set_if_empty("use_case", "agentic-coding", "Use case: agentic coding")
        text = text.replace("agentic coding", " ")
    elif re.search(r"\bcoding\b", text):
        set_if_empty("use_case", "coding", "Use case: coding")
        text = re.sub(r"\bcoding\b", " ", text)
    if re.search(r"\bcheap(?:est)?\b|weighted token cost|best value", text):
        set_if_empty("sort", "weighted_cost", "Sort: weighted token cost")
        text = re.sub(r"\bcheap(?:est)?\b|weighted token cost|best value", " ", text)
    if re.search(r"\b(?:newest|new)\s+(?:models?\s+)?this\s+month\b", text):
        set_if_empty("release", "month", "Release: this month")
        set_if_empty("sort", "newest", "Sort: newest")
        text = re.sub(r"\b(?:newest|new)\s+(?:models?\s+)?this\s+month\b", " ", text)
    elif re.search(r"\b(?:new|newest)\s+(?:models?\s+)?(?:this\s+week|last\s+7\s+days)\b", text):
        set_if_empty("release", "week", "Release: this week")
        set_if_empty("sort", "newest", "Sort: newest")
        text = re.sub(r"\b(?:new|newest)\s+(?:models?\s+)?(?:this\s+week|last\s+7\s+days)\b", " ", text)
    if re.search(r"\b(?:deals?|discounts?|offers?)\s+(?:right\s+now|today|available)?\b", text):
        set_if_empty("deal", "1", "Active deal")
        text = re.sub(r"\b(?:deals?|discounts?|offers?)\s+(?:right\s+now|today|available)?\b", " ", text)
    workflow_phrases = {
        "unreal engine": "unreal-engine",
        "unreal": "unreal-engine",
        "reaper": "reaper",
    }
    for phrase, workflow in workflow_phrases.items():
        if re.search(rf"\b{re.escape(phrase)}(?:\s+mcp)?\b", text):
            set_if_empty("workflow", workflow, f"Workflow: {phrase.title()}")
            set_if_empty("mcp", "1", "MCP workflow")
            text = re.sub(rf"\b{re.escape(phrase)}(?:\s+mcp)?\b", " ", text)
            break
    if "commercial use" in text:
        set_if_empty("commercial", "1", "Commercial use: available")
        text = text.replace("commercial use", " ")
    if "price per generation" in text or "per generation" in text:
        set_if_empty("price_unit", "per_generation", "Price unit: per generation")
        text = text.replace("price per generation", " ").replace("per generation", " ")
    media_phrases = ["text to 3d", "image to 3d", "image generation", "video generation", "3d generation", "3d", "audio"]
    for phrase in media_phrases:
        if phrase in text:
            if phrase == "text to 3d":
                set_if_empty("type", "3D generation", "Category: 3D generation")
                set_if_empty("text_to_3d", "1", "Text-to-3D: yes")
            elif phrase == "image to 3d":
                set_if_empty("type", "3D generation", "Category: 3D generation")
                set_if_empty("image_to_3d", "1", "Image-to-3D: yes")
            else:
                set_if_empty("type", MODEL_CATEGORIES[phrase], f"Category: {MODEL_CATEGORIES[phrase]}")
            text = text.replace(phrase, " ")
            break
    result["q"] = re.sub(r"\s+", " ", text).strip()
    return result, applied


def _yes_capability(column: str) -> str:
    return f"EXISTS (SELECT 1 FROM offering_capabilities oc WHERE oc.offering_id=o.id AND oc.capability='{column}' AND oc.state='YES')"


def route_rows(db, filters=None):
    """Return provider routes.  Every filter is explicit and URL-safe."""
    filters, _ = interpret_search(filters or {})
    try:
        limit = min(100_000, max(1, int(filters.get("limit", 100))))
    except (TypeError, ValueError):
        limit = 100
    try:
        offset = min(1_000_000, max(0, int(filters.get("offset", 0))))
    except (TypeError, ValueError):
        offset = 0
    clauses, params = ["1=1"], []
    if filters.get("offering_id") is not None:
        try:
            params.append(int(filters["offering_id"]))
        except (TypeError, ValueError):
            return []
        clauses.append("o.id=?")
    compatibility_harness_id = filters.get("_compatibility_harness_id")
    internal_scan = bool(filters.get("_scan_by_id") or compatibility_harness_id is not None)
    if internal_scan:
        try:
            params.append(max(0, int(filters.get("_after_offering_id", 0))))
        except (TypeError, ValueError):
            return []
        clauses.append("o.id > ?")
    if compatibility_harness_id is not None:
        try:
            compatibility_harness_id = int(compatibility_harness_id)
        except (TypeError, ValueError):
            return []
        params.append(compatibility_harness_id)
        clauses.append("""(
          EXISTS (SELECT 1 FROM route_compatibility_evidence e WHERE e.harness_id=? AND e.offering_id=o.id
            AND e.mcp_workflow_status IN ('COMPATIBLE','COMPATIBLE_WITH_CONFIGURATION','PARTIAL'))
          OR EXISTS (SELECT 1 FROM harness_model_overrides x WHERE x.harness_id=?
            AND (x.offering_id=o.id OR (x.offering_id IS NULL AND x.model_id=m.id))
            AND x.status IN ('COMPATIBLE','COMPATIBLE_WITH_CONFIGURATION','PARTIAL'))
          OR EXISTS (SELECT 1 FROM harness_provider_compatibility hp WHERE hp.harness_id=?
            AND hp.provider_id=o.provider_id AND hp.support_mode NOT IN ('NO','UNKNOWN'))
          OR EXISTS (SELECT 1 FROM harness_access_methods ha WHERE ha.harness_id=?
            AND ha.access_method='OPENROUTER' AND ha.state='YES' AND lower(p.name)='openrouter')
          OR EXISTS (SELECT 1 FROM provider_protocol_evidence pe JOIN harness_protocol_support hs
            ON hs.protocol=pe.protocol WHERE pe.provider_id=o.provider_id AND pe.state='YES'
            AND hs.harness_id=? AND hs.state='YES')
        )""")
        params.extend([compatibility_harness_id] * 4)
    if filters.get("model_id") is not None:
        clauses.append("m.id=?")
        try:
            params.append(int(filters["model_id"]))
        except (TypeError, ValueError):
            return []
    model_ids = filters.get("model_ids")
    if model_ids is not None:
        model_ids = [int(value) for value in model_ids]
        if not model_ids:
            return []
        clauses.append(f"m.id IN ({','.join('?' for _ in model_ids)})")
        params.extend(model_ids)
    if filters.get("provider_id") is not None:
        clauses.append("COALESCE(p.canonical_provider_id,p.id)=?")
        try:
            params.append(int(filters["provider_id"]))
        except (TypeError, ValueError):
            return []
    q = filters.get("q", "").strip()
    if q:
        normalized_q = re.sub(r"[\s._-]+", "", q.lower())
        clauses.append("(lower(m.canonical_name) LIKE ? OR lower(o.api_model_id) LIKE ? OR lower(COALESCE(cp.name,p.name)) LIKE ? OR lower(COALESCE(l.name,m.vendor)) LIKE ? OR replace(replace(replace(replace(lower(m.canonical_name),' ',''),'-',''),'.',''),'_','') LIKE ? OR replace(replace(replace(replace(lower(o.api_model_id),' ',''),'-',''),'.',''),'_','') LIKE ?)")
        params += [f"%{q.lower()}%"] * 4 + [f"%{normalized_q}%"] * 2
    for key, column in (("lab", "COALESCE(l.name,m.vendor)"), ("provider", "COALESCE(cp.name,p.name)"), ("status", "m.status")):
        if filters.get(key) and filters[key] != "any":
            clauses.append(f"{column}=?")
            params.append(filters[key])
    if filters.get("type") and filters["type"] != "any":
        wanted = filters["type"].casefold()
        matching_ids = [r[0] for r in db.execute("SELECT id,modality,canonical_name FROM models")
                        if modality_category(r[1], r[2]).casefold() == wanted]
        if matching_ids:
            clauses.append(f"m.id IN ({','.join('?' for _ in matching_ids)})")
            params.extend(matching_ids)
        else:
            clauses.append("m.modality=?")
            params.append(filters["type"])
    if filters.get("release") == "week":
        clauses.append("m.released_at >= ?")
        params.append((date.today() - timedelta(days=7)).isoformat())
    elif filters.get("release") == "month":
        clauses.append("m.released_at >= ?")
        params.append(date.today().replace(day=1).isoformat())
    for key, field in (("input_max", "input_price"), ("output_max", "output_price")):
        if filters.get(key):
            try:
                value = float(filters[key])
            except (TypeError, ValueError):
                raise ValueError(f"Invalid {key} filter: expected a non-negative price.")
            if value < 0:
                raise ValueError(f"Invalid {key} filter: expected a non-negative price.")
            clauses.append(f"{field} IS NOT NULL AND {field} <= ?")
            params.append(value)
    for key, column in (("context", "o.context_limit"), ("max_output", "o.max_output_tokens")):
        if filters.get(key):
            try:
                value = normalize_context(filters[key]) if key == "context" else int(filters[key])
            except (TypeError, ValueError):
                raise ValueError(f"Invalid {key} filter: expected a positive token count.")
            if value <= 0:
                raise ValueError(f"Invalid {key} filter: expected a positive token count.")
            clauses.append(f"{column} >= ?")
            params.append(value)
    if filters.get("free") == "1":
        clauses.append("(o.access_semantics IN ('FREE_API','FREE_TIER','PROMOTIONAL_FREE','TRIAL_CREDIT') AND input_price=0 AND output_price=0)")
    if filters.get("included") == "1":
        clauses.append("o.access_semantics='INCLUDED_WITH_SUBSCRIPTION'")
    if filters.get("deal") == "1":
        clauses.append("EXISTS (SELECT 1 FROM offers x WHERE x.provider_id=p.id AND (x.offering_id IS NULL OR x.offering_id=o.id) AND x.status='ACTIVE' AND (x.starts_at IS NULL OR x.starts_at<=date('now')) AND (x.ends_at IS NULL OR x.ends_at>=date('now')))")
    if filters.get("subscription") == "1":
        clauses.append("EXISTS (SELECT 1 FROM plans pl WHERE pl.provider_id=p.id)")
    if filters.get("tools") == "1":
        clauses.append("o.tool_support='YES'")
    if filters.get("structured") == "1":
        clauses.append("o.structured_output_support='YES'")
    if filters.get("open_weights") == "1":
        clauses.append("m.open_weights=1")
    if filters.get("commercial") == "1":
        clauses.append("o.commercial_use IN ('YES','CONDITIONAL')")
    if filters.get("price_unit"):
        clauses.append("EXISTS (SELECT 1 FROM pricing_records pu WHERE pu.offering_id=o.id AND pu.valid_until IS NULL AND pu.unit=?)")
        params.append(filters["price_unit"])
    for key, column in (("text_to_3d", "text_to_3d"), ("image_to_3d", "image_to_3d")):
        if filters.get(key) == "1":
            clauses.append(f"EXISTS (SELECT 1 FROM model_media_features mf WHERE mf.model_id=m.id AND mf.{column}='YES')")
    for key, capability in (("reasoning", "reasoning"), ("vision", "vision"), ("caching", "caching"), ("batch", "batch")):
        if filters.get(key) == "1":
            clauses.append(_yes_capability(capability))
    if filters.get("mcp") == "1":
        clauses.append("o.tool_support='YES'")
    if filters.get("use_case"):
        clauses.append("EXISTS (SELECT 1 FROM model_use_case_scores mus JOIN use_cases u ON u.id=mus.use_case_id WHERE mus.model_id=m.id AND u.slug=? AND mus.classification IN ('RECOMMENDED','SUPPORTED'))")
        params.append(filters["use_case"])
    access = filters.get("access")
    if access == "openrouter":
        clauses.append("p.name='OpenRouter'")
    elif access == "direct":
        clauses.append("p.name != 'OpenRouter'")
    elif access == "free":
        clauses.append("(o.access_semantics IN ('FREE_API','FREE_TIER','PROMOTIONAL_FREE','TRIAL_CREDIT') AND input_price=0 AND output_price=0)")
    order_clause = "o.id ASC" if internal_scan else """
          CASE WHEN ?='featured' THEN CASE WHEN o.tool_support='YES' THEN 0 ELSE 1 END ELSE 0 END,
          CASE WHEN ?='featured' THEN (SELECT COUNT(*) FROM provider_offerings coverage WHERE coverage.model_id=m.id) ELSE 0 END DESC,
          CASE WHEN ?='featured' THEN CASE WHEN m.released_at IS NULL THEN 1 ELSE 0 END ELSE 0 END,
          CASE WHEN ?='featured' THEN m.released_at END DESC,
          CASE WHEN ?='featured' THEN CASE WHEN active_deal THEN 0 ELSE 1 END ELSE 0 END,
          CASE WHEN ?='weighted_cost' THEN CASE WHEN input_price IS NULL OR output_price IS NULL THEN 1 ELSE 0 END ELSE 0 END,
          CASE WHEN ?='weighted_cost' THEN (0.7*input_price + 0.3*output_price) END,
          CASE WHEN ?='newest' THEN m.released_at END DESC,
          media_price IS NULL, input_price IS NULL, COALESCE(media_price,input_price), output_price, m.canonical_name, p.name
        """
    sql = f"""
        SELECT o.id offering_id,o.api_model_id,o.context_limit,o.max_output_tokens,o.tool_support,
          o.structured_output_support,o.free_status,o.access_semantics,o.access_requirement,o.caveat,o.fetched_at,m.id model_id,
          o.rate_limit_note,o.privacy_caveat,o.commercial_use,o.first_seen_at,
          o.lifecycle_status,o.last_seen_at,o.last_verified_at,
          (SELECT name FROM sources WHERE id=o.source_id) route_source_name,
          (SELECT url FROM sources WHERE id=o.source_id) route_source_url,
          m.canonical_name,m.canonical_slug,m.modality,m.open_weights,m.status,m.released_at,m.identity_kind,
          COALESCE(l.name,m.vendor) lab_name,COALESCE(cp.id,p.id) provider_id,COALESCE(cp.name,p.name) provider_name,
          (SELECT amount FROM pricing_records pr WHERE pr.offering_id=o.id AND pr.price_type='INPUT' AND pr.valid_until IS NULL ORDER BY (pr.context_threshold IS NOT NULL),pr.context_threshold,pr.valid_from DESC,pr.id DESC LIMIT 1) input_price,
          (SELECT amount FROM pricing_records pr WHERE pr.offering_id=o.id AND pr.price_type='OUTPUT' AND pr.valid_until IS NULL ORDER BY (pr.context_threshold IS NOT NULL),pr.context_threshold,pr.valid_from DESC,pr.id DESC LIMIT 1) output_price,
          (SELECT amount FROM pricing_records pr WHERE pr.offering_id=o.id AND pr.price_type='CACHE_READ' AND pr.valid_until IS NULL ORDER BY (pr.context_threshold IS NOT NULL),pr.context_threshold,pr.valid_from DESC,pr.id DESC LIMIT 1) cache_read_price,
          (SELECT price_note FROM pricing_records pr WHERE pr.offering_id=o.id AND pr.price_type='INPUT' AND pr.valid_until IS NULL ORDER BY (pr.context_threshold IS NOT NULL),pr.context_threshold,pr.valid_from DESC,pr.id DESC LIMIT 1) input_price_note,
          (SELECT price_note FROM pricing_records pr WHERE pr.offering_id=o.id AND pr.price_type='OUTPUT' AND pr.valid_until IS NULL ORDER BY (pr.context_threshold IS NOT NULL),pr.context_threshold,pr.valid_from DESC,pr.id DESC LIMIT 1) output_price_note,
          (SELECT CASE WHEN lower(s.source_type) LIKE 'official%' AND lower(s.name) NOT LIKE '%openrouter%' THEN 'official_provider' ELSE 'aggregator_observed' END FROM pricing_records pr LEFT JOIN sources s ON s.id=pr.source_id WHERE pr.offering_id=o.id AND pr.price_type='INPUT' AND pr.valid_until IS NULL ORDER BY (pr.context_threshold IS NOT NULL),pr.context_threshold,pr.valid_from DESC,pr.id DESC LIMIT 1) input_price_source_type,
          (SELECT CASE WHEN lower(s.source_type) LIKE 'official%' AND lower(s.name) NOT LIKE '%openrouter%' THEN 'official_provider' ELSE 'aggregator_observed' END FROM pricing_records pr LEFT JOIN sources s ON s.id=pr.source_id WHERE pr.offering_id=o.id AND pr.price_type='OUTPUT' AND pr.valid_until IS NULL ORDER BY (pr.context_threshold IS NOT NULL),pr.context_threshold,pr.valid_from DESC,pr.id DESC LIMIT 1) output_price_source_type,
          (SELECT amount FROM pricing_records pr WHERE pr.offering_id=o.id AND pr.price_type NOT IN ('INPUT','OUTPUT','CACHE_READ','CACHE_WRITE','BATCH_INPUT','BATCH_OUTPUT') AND pr.valid_until IS NULL ORDER BY pr.valid_from DESC,pr.id DESC LIMIT 1) media_price,
          (SELECT unit FROM pricing_records pr WHERE pr.offering_id=o.id AND pr.price_type NOT IN ('INPUT','OUTPUT','CACHE_READ','CACHE_WRITE','BATCH_INPUT','BATCH_OUTPUT') AND pr.valid_until IS NULL ORDER BY pr.valid_from DESC,pr.id DESC LIMIT 1) media_price_unit,
          (SELECT price_type FROM pricing_records pr WHERE pr.offering_id=o.id AND pr.price_type NOT IN ('INPUT','OUTPUT','CACHE_READ','CACHE_WRITE','BATCH_INPUT','BATCH_OUTPUT') AND pr.valid_until IS NULL ORDER BY pr.valid_from DESC,pr.id DESC LIMIT 1) media_price_type,
          {_yes_capability('reasoning')} reasoning, {_yes_capability('vision')} vision,
          {_yes_capability('caching')} caching, {_yes_capability('batch')} batch,
          EXISTS (SELECT 1 FROM offers x WHERE x.provider_id=p.id AND (x.offering_id IS NULL OR x.offering_id=o.id) AND x.status='ACTIVE' AND (x.starts_at IS NULL OR x.starts_at<=date('now')) AND (x.ends_at IS NULL OR x.ends_at>=date('now'))) active_deal,
          (SELECT COUNT(*) FROM offers x WHERE x.offering_id=o.id AND x.route_variant_id IS NOT NULL AND x.status='ACTIVE' AND (x.starts_at IS NULL OR x.starts_at<=date('now')) AND (x.ends_at IS NULL OR x.ends_at>=date('now'))) deal_route_count,
          (SELECT GROUP_CONCAT(DISTINCT rv.upstream_provider) FROM offers x JOIN openrouter_route_variants rv ON rv.id=x.route_variant_id WHERE x.offering_id=o.id AND x.status='ACTIVE') deal_providers
        FROM provider_offerings o JOIN models m ON m.id=o.model_id JOIN providers p ON p.id=o.provider_id
          LEFT JOIN providers cp ON cp.id=p.canonical_provider_id
          LEFT JOIN labs l ON l.id=m.lab_id
        WHERE {' AND '.join(clauses)}
        ORDER BY {order_clause}
        LIMIT ? OFFSET ?
    """
    sort = filters.get("sort", "price")
    if sort == "value":  # Backward compatibility for existing saved searches.
        sort = "weighted_cost"
    query_params = [*params]
    if not internal_scan:
        query_params.extend([sort] * 8)
    result = [dict(row) for row in db.execute(
        sql, [*query_params, limit, 0 if internal_scan else offset]
    ).fetchall()]
    for row in result:
        row["weighted_cost"] = (
            0.7 * row["input_price"] + 0.3 * row["output_price"]
            if row["input_price"] is not None and row["output_price"] is not None
            else None
        )
    return result


def filter_options(db):
    return {
        "labs": [r[0] for r in db.execute("SELECT name FROM labs ORDER BY name")],
        "providers": [r[0] for r in db.execute("SELECT name FROM providers WHERE canonical_provider_id IS NULL ORDER BY name")],
        "types": sorted({modality_category(r[0], r[1]) for r in db.execute("SELECT modality,canonical_name FROM models")}),
        "use_cases": [dict(r) for r in db.execute("SELECT slug,name FROM use_cases ORDER BY name")],
        "harnesses": [dict(r) for r in db.execute("SELECT id,name FROM harnesses ORDER BY name")],
        "workflows": [dict(r) for r in db.execute("SELECT id,slug,name FROM workflows ORDER BY name")],
    }


def price_history(db, offering_id):
    rows = [dict(r) for r in db.execute(
        """SELECT pr.*,s.name source_name,s.url source_url
           FROM pricing_records pr LEFT JOIN sources s ON s.id=pr.source_id
           WHERE pr.offering_id=? ORDER BY pr.price_type,pr.valid_from DESC,pr.id DESC""",
        (offering_id,),
    )]
    grouped = {}
    for row in rows:
        key = (row["price_type"], row["unit"], row["context_threshold"], row["price_note"])
        grouped.setdefault(key, []).append(row)
    summaries = []
    for (price_type, unit, threshold, note), records in grouped.items():
        current = next((r for r in records if r["valid_until"] is None), None)
        reference = current or records[0]
        previous = next((r for r in records if r["id"] != reference["id"] and r["amount"] != reference["amount"]), None)
        prior = previous["amount"] if previous else None
        change = ((reference["amount"] - prior) / prior * 100) if current and prior not in (None, 0) else None
        summaries.append({
            "price_type": price_type,
            "unit": unit,
            "currency": reference["currency"],
            "current": current["amount"] if current else None,
            "previous": prior,
            "change_percent": change,
            "change_amount": (reference["amount"] - prior) if prior is not None else None,
            "date_changed": reference["valid_from"],
            "lowest": min(r["amount"] for r in records),
            "context_threshold": threshold,
            "price_note": note,
            "records": records,
        })
    return sorted(summaries, key=lambda item: item["price_type"])


def offer_rows(db, include_expired=False):
    condition = "1=1" if include_expired else "x.status='ACTIVE' AND (x.starts_at IS NULL OR x.starts_at<=date('now')) AND (x.ends_at IS NULL OR x.ends_at>=date('now'))"
    return [dict(r) for r in db.execute(f"""
      SELECT x.*,p.name provider_name,o.api_model_id,m.canonical_name,o.tool_support,
        o.context_limit,o.access_semantics,o.access_requirement,o.rate_limit_note,o.privacy_caveat route_privacy_caveat,
        rv.upstream_provider,rv.provider_tag,rv.endpoint_status,rv.quantization,
        s.name source_name,s.url source_url,s.source_type source_type
      FROM offers x JOIN providers p ON p.id=x.provider_id
      LEFT JOIN provider_offerings o ON o.id=x.offering_id
      LEFT JOIN models m ON m.id=o.model_id
      LEFT JOIN openrouter_route_variants rv ON rv.id=x.route_variant_id
      LEFT JOIN sources s ON s.id=x.source_id
      WHERE {condition}
      ORDER BY x.status='ACTIVE' DESC,x.last_verified_at DESC,p.name,x.title
    """).fetchall()]


def plan_rows(db, filters=None):
    """Return current developer plans without interpreting vague allowances."""
    filters = filters or {}
    clauses, params = ["pl.status IN ('ACTIVE','LIMITED','WAITLIST')"], []
    if filters.get("coding") == "1":
        clauses.append("pl.is_coding=1")
    if filters.get("api") == "1":
        clauses.append("pl.api_access IN ('YES','LIMITED')")
    if filters.get("subscription") == "1":
        clauses.append("pl.plan_type='SUBSCRIPTION'")
    if filters.get("free") == "1":
        clauses.append("(pl.plan_type='FREE' OR pl.monthly_price=0)")
    if filters.get("provider"):
        clauses.append("lower(p.name)=lower(?)")
        params.append(filters["provider"])
    if filters.get("harness"):
        clauses.append("EXISTS (SELECT 1 FROM plan_harness_compatibility ph JOIN harnesses h ON h.id=ph.harness_id WHERE ph.plan_id=pl.id AND lower(h.name)=lower(?) AND ph.support_level!='UNSUPPORTED')")
        params.append(filters["harness"])
    if filters.get("max_price") not in (None, ""):
        try:
            maximum = max(0, float(filters["max_price"]))
        except (TypeError, ValueError):
            maximum = None
        if maximum is not None:
            clauses.append("pl.monthly_price<=?")
            params.append(maximum)
    rows = db.execute(f"""
      SELECT pl.*,p.name provider_name,s.name source_name,s.url source_url,
        GROUP_CONCAT(DISTINCT h.name) compatible_harnesses
      FROM plans pl JOIN providers p ON p.id=pl.provider_id
      LEFT JOIN sources s ON s.id=pl.source_id
      LEFT JOIN plan_harness_compatibility ph ON ph.plan_id=pl.id AND ph.support_level!='UNSUPPORTED'
      LEFT JOIN harnesses h ON h.id=ph.harness_id
      WHERE {' AND '.join(clauses)}
      GROUP BY pl.id
      ORDER BY pl.monthly_price IS NULL,pl.monthly_price,p.name,pl.name
    """, params).fetchall()
    result = [dict(row) for row in rows]
    for plan in result:
        plan["compatibility"] = [dict(item) for item in db.execute("""
          SELECT h.name harness_name,ph.support_level,ph.note,s.url source_url
          FROM plan_harness_compatibility ph JOIN harnesses h ON h.id=ph.harness_id
          JOIN sources s ON s.id=ph.source_id WHERE ph.plan_id=? ORDER BY h.name
        """, (plan["id"],)).fetchall()]
    return result


def access_route_rows(db):
    return [dict(row) for row in db.execute("""
      SELECT ar.*,p.name provider_name,pl.name plan_name,s.name source_name,s.url source_url
      FROM model_access_routes ar
      LEFT JOIN providers p ON p.id=ar.provider_id
      LEFT JOIN plans pl ON pl.id=ar.plan_id
      JOIN sources s ON s.id=ar.source_id
      ORDER BY ar.model_family,CASE ar.route_type WHEN 'SUBSCRIPTION' THEN 0 WHEN 'DIRECT_API' THEN 1 ELSE 2 END,ar.route_name
    """).fetchall()]


def openrouter_free_rows(db, tools_only=False):
    condition = "AND rv.tool_support='YES'" if tools_only else ""
    return [dict(row) for row in db.execute(f"""
      SELECT rv.*,m.canonical_name,m.canonical_slug,o.api_model_id,
        CASE WHEN instr(COALESCE(rv.input_modalities_json,''),'image')>0 THEN 'YES' ELSE 'NO' END vision_support
      FROM openrouter_route_variants rv
      JOIN provider_offerings o ON o.id=rv.offering_id
      JOIN models m ON m.id=o.model_id
      WHERE rv.is_free=1 AND rv.endpoint_status=0 {condition}
      ORDER BY rv.tool_support='YES' DESC,m.canonical_name,rv.upstream_provider,rv.provider_tag
    """).fetchall()]


def openrouter_variant_rows(db, offering_id):
    return [dict(row) for row in db.execute("""
      SELECT * FROM openrouter_route_variants WHERE offering_id=?
      ORDER BY endpoint_status=0 DESC,input_price IS NULL,input_price,output_price,upstream_provider,provider_tag
    """, (offering_id,)).fetchall()]


def pricing_differences(db):
    cache = [dict(r) for r in db.execute("""
      SELECT o.id offering_id,m.canonical_name,p.name provider_name,
        i.amount input_price,c.amount discounted_price,'Cache read' discount_type,
        ROUND((1-c.amount/i.amount)*100,1) savings_percent,s.url source_url
      FROM provider_offerings o JOIN models m ON m.id=o.model_id JOIN providers p ON p.id=o.provider_id
      JOIN pricing_records i ON i.id=(SELECT id FROM pricing_records WHERE offering_id=o.id AND price_type='INPUT' AND valid_until IS NULL ORDER BY valid_from DESC,id DESC LIMIT 1)
      JOIN pricing_records c ON c.id=(SELECT id FROM pricing_records WHERE offering_id=o.id AND price_type='CACHE_READ' AND valid_until IS NULL ORDER BY valid_from DESC,id DESC LIMIT 1)
      LEFT JOIN sources s ON s.id=c.source_id WHERE i.amount>0 AND c.amount<i.amount
      ORDER BY savings_percent DESC LIMIT 50
    """).fetchall()]
    direct = [dict(r) for r in db.execute("""
      SELECT m.canonical_name,d.id direct_id,dp.name direct_provider,di.amount direct_input,
        a.id aggregator_id,ai.amount aggregator_input,
        ROUND(ai.amount-di.amount,4) difference
      FROM models m JOIN provider_offerings d ON d.model_id=m.id
      JOIN providers dp ON dp.id=d.provider_id AND dp.name!='OpenRouter'
      JOIN provider_offerings a ON a.model_id=m.id JOIN providers ap ON ap.id=a.provider_id AND ap.name='OpenRouter'
      JOIN pricing_records di ON di.id=(SELECT id FROM pricing_records WHERE offering_id=d.id AND price_type='INPUT' AND valid_until IS NULL ORDER BY valid_from DESC,id DESC LIMIT 1)
      JOIN pricing_records ai ON ai.id=(SELECT id FROM pricing_records WHERE offering_id=a.id AND price_type='INPUT' AND valid_until IS NULL ORDER BY valid_from DESC,id DESC LIMIT 1)
      ORDER BY ABS(ai.amount-di.amount) DESC LIMIT 50
    """).fetchall()]
    return {"discounts": cache, "direct": direct}


def ranking_groups(db):
    """Factual lists with an explicit metric; never a universal model score."""
    from .benchmark_queries import comparable_groups

    routes = route_rows(db, {"limit": 250})
    benchmark_rows = [dict(r) for r in db.execute("""
      SELECT b.name,b.version,b.category,br.metric,br.task_subset,br.harness_name,br.scaffold,
        br.reasoning_setting,br.tool_policy,br.network_policy,br.score,br.confidence,m.id model_id,
        m.canonical_name,s.name source_name,s.url source_url
      FROM benchmark_results br JOIN benchmarks b ON b.id=br.benchmark_id
      JOIN models m ON m.id=br.model_id LEFT JOIN sources s ON s.id=br.source_id
      WHERE br.confidence IN ('HIGH','MEDIUM') AND b.is_current=1
      ORDER BY b.name,b.version,br.metric,br.task_subset,br.harness_name,br.scaffold,
        br.reasoning_setting,br.tool_policy,br.network_policy,br.score DESC
    """).fetchall()]
    benchmark_groups = []
    for group in comparable_groups(benchmark_rows):
        name, version, metric = group["benchmark"], group["version"], group["metric"]
        config = ", ".join(str(value) for value in group["configuration"].values())
        benchmark_groups.append({
            "title": f"{name} {version}" + (f" · {config}" if config else ""),
            "metric": f"{metric}; same benchmark version and recorded configuration only.",
            "kind": "benchmark", "rows": sorted(group["results"], key=lambda row: row["score"], reverse=True)[:8],
        })
    benchmark_groups = benchmark_groups[:16]
    weighted_cost = [r for r in route_rows(db, {"tools": "1", "use_case": "coding", "sort": "weighted_cost", "limit": 8}) if r["weighted_cost"] is not None]
    cheapest = [r for r in route_rows(db, {"tools": "1", "limit": 8}) if r["input_price"] is not None]
    return [
        *benchmark_groups,
        {"title": "Lowest estimated token cost for coding routes", "metric": "Weighted token cost: 0.70 × input $/M + 0.30 × output $/M among routes with tools. This is a cost estimate, not quality.", "kind": "route", "rows": weighted_cost},
        {"title": "Cheapest tool-capable routes", "metric": "Current input $/M, then output $/M; no quality score.", "kind": "route", "rows": cheapest},
        {"title": "Free models with tools", "metric": "Exact routes with current input and output prices both recorded as $0 and tool calling=YES.", "kind": "route", "rows": route_rows(db, {"free": "1", "tools": "1", "limit": 8})},
        {"title": "Long-context + tools", "metric": "Documented context window descending, with tool calling=YES.", "kind": "route", "rows": sorted([r for r in routes if r["tool_support"] == "YES"], key=lambda r: r["context_limit"] or 0, reverse=True)[:8]},
    ]


def source_rows(db, offering_id=None, model_id=None):
    source_queries, params = [], []
    if offering_id:
        source_queries.extend([
            "SELECT source_id FROM provider_offerings WHERE id=?",
            "SELECT source_id FROM pricing_records WHERE offering_id=?",
            "SELECT source_id FROM offering_capabilities WHERE offering_id=?",
        ])
        params += [offering_id] * 3
    if model_id:
        source_queries.extend([
            "SELECT source_id FROM provider_offerings WHERE model_id=?",
            "SELECT source_id FROM benchmark_results WHERE model_id=?",
        ])
        params += [model_id] * 2
    if not source_queries:
        return [dict(r) for r in db.execute("SELECT name,url,reliability FROM sources ORDER BY name")]
    ids = " UNION ".join(source_queries)
    return [dict(r) for r in db.execute(
        f"SELECT name,url,reliability FROM sources WHERE id IN ({ids}) ORDER BY name", params
    ).fetchall()]

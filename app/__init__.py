import os
import re
import secrets
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, abort, g, jsonify, redirect, render_template, request, url_for

from .db import init_db
from .domain import compatibility_for, compatible_route_rows
from .public import absolute_url, public, slugify
from .query import (
    access_route_rows,
    filter_options,
    interpret_search,
    modality_category,
    normalize_context,
    offer_rows,
    openrouter_free_rows,
    openrouter_variant_rows,
    plan_rows,
    price_history,
    pricing_differences,
    ranking_groups,
    route_rows,
    source_rows,
)

NAV = [("Home", "/"), ("Models", "/models"), ("My Setup", "/my-setup"),
       ("Compare", "/compare"), ("Offers", "/deals"), ("Calculator", "/calculator")]
MORE_NAV = [("Compatibility", "/compatibility"), ("Plans", "/plans"),
            ("New Releases", "/releases"), ("Harnesses", "/harnesses"),
            ("Workflows", "/workflows"), ("Benchmarks", "/benchmarks"),
            ("Providers", "/providers"), ("Use Cases", "/use-cases"),
            ("Rankings", "/rankings"), ("API", "/api"), ("MCP", "/mcp-info")]
PRESETS = {
    "free-tools": ("Free + Tools", {"free": "1", "tools": "1"}), "cheap-agent": ("Cheapest Agent Models", {"tools": "1", "use_case": "agentic-coding"}),
    "strong-coding": ("Strong Coding", {"tools": "1", "use_case": "coding"}), "lowest-token-cost-coding": ("Lowest Token Cost for Coding", {"tools": "1", "use_case": "coding", "sort": "weighted_cost"}),
    "million-tools": ("1M Context + Tools", {"context": "1000000", "tools": "1"}), "open-tools": ("Open Weight + Tools", {"open_weights": "1", "tools": "1"}),
    "new-week": ("New This Week", {"release": "week"}), "discounts": ("Current Discounts", {"deal": "1"}), "hermes": ("Works With Hermes", {"harness": "Hermes Agent"}),
    "opencode": ("Works With OpenCode", {"harness": "OpenCode"}), "pi": ("Works With Pi", {"harness": "Pi"}), "codex": ("Works With Codex", {"harness": "Codex CLI"}),
}


def human_offer_model(name):
    """Trim provider prefixes and catalog date suffixes from compact offer titles."""
    value = str(name or "AI model").strip()
    value = re.sub(r"^(?:DeepSeek|Anthropic|OpenAI|Google|Qwen|Alibaba|Mistral|Moonshot|MiniMax|Inception|inclusionAI|Z\.ai)\s*:\s*", "", value, flags=re.I)
    return re.sub(r"\s+(?:20\d{2}|\d{4})$", "", value)


def price_history_chart(records):
    """Return SVG coordinates only for recorded observations on two or more dates."""
    dated = []
    for record in records:
        try:
            observed = date.fromisoformat(str(record.get("valid_from", ""))[:10])
            amount = float(record["amount"])
        except (TypeError, ValueError, KeyError):
            continue
        dated.append((observed, amount))
    dated.sort(key=lambda item: item[0])
    if len(dated) < 2:
        return None
    first, last = dated[0][0], dated[-1][0]
    span_days = max((last - first).days, 1)
    low, high = min(amount for _, amount in dated), max(amount for _, amount in dated)
    points = []
    for observed, amount in dated:
        x = 12 + 296 * (observed - first).days / span_days
        y = 52 - 40 * ((amount - low) / (high - low) if high != low else 0.5)
        points.append(f"{x:.1f},{y:.1f}")
    return {"points": " ".join(points), "start": first.isoformat(), "end": last.isoformat()}


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.getenv("FLASK_SECRET_KEY", "local-development-key"),
        DATABASE=os.getenv("DATABASE_PATH", str(Path(app.instance_path) / "usethismodel.sqlite3")),
        PUBLIC_BASE_URL=os.getenv("PUBLIC_BASE_URL", "").rstrip("/"),
    )
    if test_config:
        app.config.update(test_config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    init_db(app)
    app.register_blueprint(public)
    app.jinja_env.globals["slugify"] = slugify
    app.jinja_env.globals["modality_category"] = modality_category

    @app.before_request
    def content_security_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.before_request
    def redirect_obsolete_hosts():
        """Keep alternate production hosts out of the public index."""
        host = request.host.split(":", 1)[0].lower()
        if host in {"usethismodel.codefiction.net", "www.usethismodel.com"}:
            target = "https://usethismodel.com" + request.path
            if request.query_string:
                target += "?" + request.query_string.decode("ascii", "replace")
            return redirect(target, code=308)
    if app.config.get("APPLY_DATA_SNAPSHOT", not app.config.get("TESTING", False)):
        from .data_snapshot import apply_snapshot
        from .db import get_db
        with app.app_context():
            apply_snapshot(get_db(), Path(__file__).resolve().parent.parent / "data" / "catalog.json")

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Content-Security-Policy", f"default-src 'self'; style-src 'self'; script-src 'self' 'nonce-{g.csp_nonce}'; img-src 'self' data:; connect-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
        # Browsers ignore HSTS on plain HTTP; emitting it unconditionally also
        # covers TLS terminated by Coolify's reverse proxy.
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.path.startswith("/internal/") or request.path.startswith("/api/v1/"):
            response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
        if request.method == "GET" and (request.path == "/api/v1" or request.path.startswith("/api/v1/")):
            response.headers.setdefault("Cache-Control", "public, max-age=60, stale-while-revalidate=30")
        return response

    @app.after_request
    def anonymous_analytics(response):
        """Count product actions without retaining queries, prompts, IPs, or cookies."""
        if response.status_code >= 400 or request.method != "GET" or request.headers.get("DNT") == "1":
            return response
        agent = request.headers.get("User-Agent", "").lower()
        if any(token in agent for token in ("bot", "crawler", "spider", "slurp")):
            return response
        from .analytics import record
        event = dimension = None
        if request.endpoint == "model_detail_slug":
            event, dimension = "model_view", request.view_args.get("model_slug", "")
        elif request.endpoint == "harness_detail_slug":
            event, dimension = "harness_view", request.view_args.get("harness_slug", "")
        elif request.endpoint == "compare":
            compared = [value for raw in request.args.getlist("ids") for value in raw.split(",") if value]
            event, dimension = "comparison", str(min(5, len(compared)))
        elif request.path.startswith("/api/v1/"):
            event, dimension = "api_request", request.path.removeprefix("/api/v1/").split("/", 1)[0]
        elif request.args.get("q"):
            event, dimension = "search", request.endpoint or "unknown"
        elif request.args:
            safe_keys = sorted(key for key in request.args if key in {
                "provider", "tools", "free", "open_weights", "context", "max_output",
                "input_max", "output_max", "use_case", "harness", "workflow", "deal",
                "release", "type", "reasoning", "vision", "caching", "batch", "sort",
            })
            if safe_keys:
                event, dimension = "filters", ",".join(safe_keys)
        if event:
            try:
                record(db(), event, dimension)
            except Exception:
                app.logger.exception("anonymous analytics write failed")
        return response

    @app.post("/analytics/event")
    def analytics_event():
        from .analytics import record
        payload = request.get_json(silent=True) or {}
        if payload.get("event") != "deal_click":
            abort(400)
        record(db(), "deal_click", slugify(payload.get("provider", "unknown")))
        return ("", 204)

    @app.context_processor
    def navigation():
        from .data_quality import freshness_text
        canonical = absolute_url(request.path)
        return {
            "nav": NAV,
            "more_nav": MORE_NAV,
            "more_active": any(request.path == url or request.path.startswith(url + "/")
                               for _, url in MORE_NAV),
            "current_path": request.path,
            "presets": PRESETS,
            "canonical_url": canonical,
            "meta_description": "Compare AI models by exact provider route, current price, capabilities, harness compatibility, sources, and verification date.",
            "robots_meta": "noindex,follow" if request.args else "index,follow",
            "csp_nonce": g.csp_nonce,
            "freshness_text": freshness_text,
            "human_offer_model": human_offer_model,
            "resolve_logo": __import__("app.logo_system", fromlist=["resolve_logo"]).resolve_logo,
            "logo": __import__("app.logo_system", fromlist=["logo_html"]).logo_html,
        }

    def db():
        from .db import get_db
        return get_db()

    def rows(query, params=()):
        return db().execute(query, params).fetchall()

    def require_internal_access():
        token = os.getenv("INTERNAL_DASHBOARD_TOKEN", "")
        supplied = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if not token or not secrets.compare_digest(token, supplied):
            abort(404)

    def finder_filters():
        return {key: value for key, value in request.args.items() if value not in ("", "any", None)}

    def interpreted_filters():
        return interpret_search(finder_filters())

    def compatible_routes(filters):
        harness_names = [name for name in filters.get("harnesses", "").split(",") if name]
        if filters.get("harness"):
            harness_names.insert(0, filters["harness"])
        all_harnesses = rows("SELECT id,name FROM harnesses ORDER BY id")
        normalized_names = []
        for value in harness_names:
            candidate = next((h for h in all_harnesses
                              if str(h["id"]) == value or h["name"].lower() == value.lower()
                              or slugify(h["name"]) == slugify(value)), None)
            if not candidate:
                raise ValueError(f"Unknown harness: {value}")
            normalized_names.append(candidate["name"])
        harness_names = normalized_names
        harness_names = list(dict.fromkeys(harness_names))
        try:
            requested_limit = min(250, max(1, int(filters.get("limit", 100))))
        except (TypeError, ValueError):
            requested_limit = 100
        try:
            requested_offset = max(0, int(filters.get("offset", 0)))
        except (TypeError, ValueError):
            requested_offset = 0
        workflow = None
        workflow_only = False
        if filters.get("workflow"):
            workflow = db().execute(
                "SELECT id,name,slug FROM workflows WHERE slug=? OR name=?",
                (filters["workflow"], filters["workflow"]),
            ).fetchone()
            if not workflow:
                raise ValueError(f"Unknown workflow: {filters['workflow']}")
            if not harness_names:
                workflow_only = True
                harness_names = [row["name"] for row in db().execute("""SELECT DISTINCT h.name
                  FROM workflow_harness_compatibility whc
                  JOIN workflow_integrations wi ON wi.id=whc.integration_id
                  JOIN harnesses h ON h.id=whc.harness_id
                  WHERE wi.workflow_id=? AND whc.state IN ('YES','CONFIGURATION','PARTIAL')""",
                  (workflow["id"],)).fetchall()]
        route_filters = {key: value for key, value in filters.items() if key != "workflow"}
        if not harness_names:
            return route_rows(db(), route_filters)
        harnesses = [db().execute("SELECT id,name FROM harnesses WHERE name=?", (name,)).fetchone() for name in harness_names]
        if any(not harness for harness in harnesses):
            return []
        qualified = [compatible_route_rows(
            db(), route_filters, harness["id"], workflow["id"] if workflow else None,
            filters.get("mcp") == "1" or workflow is not None,
        ) for harness in harnesses]
        by_harness = [{row["offering_id"]: row for row in group} for group in qualified]
        ids = (set().union(*(set(group) for group in by_harness)) if workflow_only
               else set.intersection(*(set(group) for group in by_harness)))
        kept = []
        for offering_id in sorted(ids):
            route = next(group[offering_id] for group in by_harness if offering_id in group)
            matches = [(harness["name"], group[offering_id]["_compatibility"])
                       for harness, group in zip(harnesses, by_harness) if offering_id in group]
            match = matches[0][1]
            if len(matches) > 1 and not workflow_only:
                match = {**match, "explanation": " ".join(
                    f"{name}: {value['explanation']}" for name, value in matches
                )}
            route["compatibility"] = match
            kept.append(route)
        kept.sort(key=lambda row: (row.get("input_price") is None, row.get("input_price") or 0,
                                   row.get("canonical_name", ""), row.get("provider_name", "")))
        return kept[requested_offset:requested_offset + requested_limit]

    @app.get("/health")
    def health():
        db().execute("SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1").fetchone()
        snapshot = db().execute("SELECT digest FROM applied_snapshots ORDER BY applied_at DESC LIMIT 1").fetchone()
        return jsonify(status="ok", database="sqlite", catalog_snapshot_digest=snapshot[0] if snapshot else None)

    @app.get("/health/readiness")
    def readiness():
        metrics = {
            "models": db().execute("SELECT COUNT(*) FROM models WHERE status!='DEPRECATED'").fetchone()[0],
            "routes": db().execute("SELECT COUNT(*) FROM provider_offerings WHERE lifecycle_status!='REMOVED'").fetchone()[0],
            "sources_ok": db().execute("SELECT COUNT(*) FROM source_health WHERE status='OK'").fetchone()[0],
            "sources_failed": db().execute("SELECT COUNT(*) FROM source_health WHERE status IN ('ERROR','QUARANTINED')").fetchone()[0],
            "documentation_sources_failed": db().execute("SELECT COUNT(*) FROM documentation_monitor_state WHERE status='ERROR'").fetchone()[0],
        }
        minimum_models = int(os.getenv("HEALTH_MIN_MODELS", "100"))
        minimum_routes = int(os.getenv("HEALTH_MIN_ROUTES", "100"))
        failures = []
        if metrics["models"] < minimum_models:
            failures.append(f"model count below {minimum_models}")
        if metrics["routes"] < minimum_routes:
            failures.append(f"route count below {minimum_routes}")
        if metrics["sources_failed"]:
            failures.append(f"{metrics['sources_failed']} source updater(s) failing")
        if metrics["documentation_sources_failed"]:
            failures.append(f"{metrics['documentation_sources_failed']} official documentation source(s) failing")
        return jsonify(status="degraded" if failures else "ok", checks=metrics, actions=failures), (503 if failures else 200)

    @app.get("/mcp-info")
    def mcp_info():
        return render_template(
            "mcp.html",
            title="MCP server",
            meta_description="Connect agents to UseThisModel's read-only, source-backed model route data over MCP.",
        )

    @app.get("/")
    def home():
        filters, interpreted = interpreted_filters()
        recent_releases = rows("""SELECT m.id,m.canonical_name,m.canonical_slug,m.vendor,m.modality,m.released_at,
          m.release_date_kind,l.name lab_name,
          (SELECT COUNT(*) FROM provider_offerings o WHERE o.model_id=m.id AND o.lifecycle_status!='REMOVED') route_count,
          (SELECT COUNT(*) FROM benchmark_results b WHERE b.model_id=m.id) benchmark_count,
          COALESCE((SELECT SUM(a.count) FROM analytics_daily a WHERE a.dimension=m.canonical_slug
             AND a.event='model_view' AND a.day>=?),0) site_activity
          FROM models m LEFT JOIN labs l ON l.id=m.lab_id
          WHERE m.released_at>=? AND m.status!='DEPRECATED'""",
          ((date.today() - timedelta(days=29)).isoformat(), (date.today() - timedelta(days=7)).isoformat()))
        # Editorial prominence is deterministic and explainable. Lab recognition is one
        # small signal; route, benchmark, official-release, and real usage evidence can
        # also make an emerging lab's release notable.
        major_labs = {"openai", "anthropic", "google", "deepseek", "z.ai", "zhipu ai",
                      "alibaba", "qwen", "moonshot", "kimi", "minimax", "mistral", "meta"}
        recent_releases = [dict(item) for item in recent_releases]
        for item in recent_releases:
            lab = (item["lab_name"] or item["vendor"] or "").casefold()
            score = (2 if any(name in lab for name in major_labs) else 0)
            score += 3 if item["route_count"] >= 3 else 2 if item["route_count"] >= 2 else 0
            score += 2 if item["benchmark_count"] else 0
            score += 2 if item["release_date_kind"] == "official" else 0
            score += min(3, int(item["site_activity"]).bit_length())
            item["prominence"] = score
            item["category"] = modality_category(item["modality"], item["canonical_name"])
        ranked_releases = sorted(recent_releases,
            key=lambda item: (item["prominence"], item["released_at"], item["canonical_name"]), reverse=True)
        latest = [item for item in ranked_releases if item["prominence"] >= 2][:3]
        def offer_rank(offer):
            kind = (offer.get("offer_type") or "").lower().replace("_", " ")
            free_route = kind in {"$0 route", "free", "free route"}
            try:
                discount = float(offer.get("discount_percent") or 0)
            except (TypeError, ValueError):
                discount = 0
            return (free_route, discount, offer.get("last_verified_at") or "")

        return render_template(
            "index.html", title="Find an AI model", filters=filters,
            interpreted=interpreted, options=filter_options(db()),
            routes=compatible_routes(filters)[:6] if filters else [],
            deals=sorted(offer_rows(db()), key=offer_rank, reverse=True)[:4], latest=latest,
            structured_data={
                "@context": "https://schema.org", "@type": "Dataset",
                "name": "UseThisModel AI model route catalog", "url": absolute_url("/"),
                "description": "Source-backed AI models, provider routes, prices, offers, harness compatibility, releases, and benchmarks.",
            },
            meta_description="Find AI models by what you need. Compare current prices, explore offers, and see what works with your tools.",
        )

    @app.get("/models")
    def models():
        filters, interpreted = interpreted_filters()
        try:
            page = max(1, int(filters.get("page", 1)))
        except (TypeError, ValueError):
            page = 1
        page_size = 18
        display_filters = dict(filters)
        if not display_filters:
            display_filters["sort"] = "featured"
        query_filters = {**display_filters, "limit": page_size + 1,
                         "offset": (page - 1) * page_size}
        filter_errors = []
        try:
            found = compatible_routes(query_filters)
        except ValueError as exc:
            found = []
            filter_errors.append(str(exc))
        page_params = {key: value for key, value in filters.items() if key != "page"}
        return render_template(
            "models.html", title="AI models", filters=display_filters,
            interpreted=interpreted, options=filter_options(db()), routes=found[:page_size],
            page=page, has_more=len(found) > page_size, default_view=not filters,
            prev_url=("/models?" + urlencode({**page_params, "page": page - 1})) if page > 1 else None,
            next_url=("/models?" + urlencode({**page_params, "page": page + 1})) if len(found) > page_size else None,
            filter_errors=filter_errors,
        )

    @app.get("/models/<int:model_id>")
    def model_detail(model_id):
        model = db().execute("SELECT m.*,l.name lab_name FROM models m LEFT JOIN labs l ON l.id=m.lab_id WHERE m.id=?", (model_id,)).fetchone()
        if not model:
            redirect_target = db().execute(
                """SELECT m.canonical_slug FROM model_identity_redirects r
                   JOIN models m ON m.id=r.target_model_id WHERE r.old_model_id=?""",
                (model_id,),
            ).fetchone()
            if redirect_target:
                return redirect(url_for("model_detail_slug", model_slug=redirect_target[0]), code=301)
            abort(404)
        return redirect(url_for("model_detail_slug", model_slug=model["canonical_slug"]), code=301)

    @app.get("/models/<path:model_slug>")
    def model_detail_slug(model_slug):
        public_aliases = {"glm-5-3": "zhipuai/glm-5.3", "deepseek-v4-pro": "deepseek/deepseek-v4-pro"}
        canonical_slug = public_aliases.get(model_slug, model_slug)
        model = db().execute("SELECT m.*,l.name lab_name FROM models m LEFT JOIN labs l ON l.id=m.lab_id WHERE m.canonical_slug=?", (canonical_slug,)).fetchone()
        if not model:
            redirect_target = db().execute(
                """SELECT m.canonical_slug FROM model_identity_redirects r
                   JOIN models m ON m.id=r.target_model_id WHERE r.old_slug=?""",
                (canonical_slug,),
            ).fetchone()
            if redirect_target:
                return redirect(url_for("model_detail_slug", model_slug=redirect_target[0]), code=301)
            abort(404)
        model_id = model["id"]
        all_offerings = route_rows(db(), {"model_id": model_id, "limit": 250})
        offerings = all_offerings[:12]
        use_cases = rows("SELECT u.name,u.slug,mus.classification,mus.rationale,mus.confidence FROM model_use_case_scores mus JOIN use_cases u ON u.id=mus.use_case_id WHERE mus.model_id=? ORDER BY u.name", (model_id,))
        benchmarks = rows("""SELECT b.id benchmark_id,b.name,b.version,b.is_current,b.published_at,
          b.last_verified_at benchmark_verified_at,br.score,br.metric,br.task_subset,br.confidence,
          br.model_version,br.harness_name,br.harness_version,br.scaffold,br.reasoning_setting,
          br.tool_policy,br.network_policy,br.evaluated_at,br.confidence_interval,
          s.name source_name,s.url source_url FROM benchmark_results br
          JOIN benchmarks b ON b.id=br.benchmark_id LEFT JOIN sources s ON s.id=br.source_id
          WHERE br.model_id=? ORDER BY b.name,b.version,br.metric,br.task_subset,br.evaluated_at DESC""", (model_id,))
        harnesses = []
        for harness in rows("SELECT id,name FROM harnesses ORDER BY name"):
            supported = [compatibility_for(db(), harness["id"], o["offering_id"]) for o in all_offerings]
            supported = [x for x in supported if x["status"] in {"COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION", "PARTIAL"}]
            if supported:
                harnesses.append({"name": harness["name"], **supported[0]})
        media = db().execute("SELECT * FROM model_media_features WHERE model_id=?", (model_id,)).fetchone()
        verified = max([o["fetched_at"] for o in all_offerings if o["fetched_at"]] + ([media["last_verified_at"]] if media and media["last_verified_at"] else []), default=None)
        canonical_path = next((alias for alias, target in public_aliases.items()
                               if target == canonical_slug), canonical_slug)
        schema = {"@context": "https://schema.org", "@type": "Dataset",
                  "name": f"{model['canonical_name']} provider routes and compatibility",
                  "description": f"Current source-backed routes, prices, capabilities and benchmark observations for {model['canonical_name']}.",
                  "url": absolute_url(url_for('model_detail_slug', model_slug=canonical_path)),
                  "dateModified": verified[:10] if verified else None}
        return render_template("model_detail.html", title=f"{model['canonical_name']} prices, providers & compatibility", item=dict(model), offerings=offerings, offering_count=len(all_offerings), use_cases=use_cases, benchmarks=benchmarks, harnesses=harnesses, media=dict(media) if media else None, sources=source_rows(db(), model_id=model_id), last_verified_at=verified, canonical_url=schema["url"], structured_data=schema, meta_description=f"{model['canonical_name']} provider routes, current pricing, limits, tool support, benchmarks, harness compatibility, sources, and verification dates.")

    @app.get("/routes/<int:offering_id>")
    def route_detail(offering_id):
        route = next(iter(route_rows(db(), {"offering_id": offering_id})), None)
        if not route:
            abort(404)
        return redirect(url_for("route_detail_slug", provider_slug=slugify(route["provider_name"]), api_model_id=route["api_model_id"]), code=301)

    @app.get("/routes/<provider_slug>/<path:api_model_id>")
    def route_detail_slug(provider_slug, api_model_id):
        provider = next((p for p in rows("SELECT id,name FROM providers") if slugify(p["name"]) == provider_slug), None)
        if not provider:
            abort(404)
        offering = db().execute("SELECT id FROM provider_offerings WHERE provider_id=? AND api_model_id=?", (provider["id"], api_model_id)).fetchone()
        if not offering:
            abort(404)
        offering_id = offering["id"]
        route = next(iter(route_rows(db(), {"offering_id": offering_id})), None)
        peers = route_rows(db(), {"model_id": route["model_id"], "limit": 250})
        offers = [o for o in offer_rows(db(), include_expired=True) if o["offering_id"] in (None, offering_id) and o["provider_id"] == route["provider_id"]]
        history = price_history(db(), offering_id)
        for item in history:
            item["chart"] = price_history_chart(item["records"])
        return render_template("route_detail.html", title=f"{route['canonical_name']} via {route['provider_name']}", route=route, history=history, peers=peers, offers=offers, route_variants=openrouter_variant_rows(db(), offering_id), sources=source_rows(db(), offering_id=offering_id), canonical_url=absolute_url(request.path), meta_description=f"Current {route['canonical_name']} pricing, limits, tool support, offers, price history, and sources for the {route['provider_name']} route.")

    @app.get("/providers")
    def providers():
        providers = rows("""SELECT p.id,p.name,p.website_url,COUNT(o.id) route_count FROM providers p
          LEFT JOIN providers alias ON alias.canonical_provider_id=p.id
          LEFT JOIN provider_offerings o ON o.provider_id IN (p.id,alias.id)
          WHERE p.canonical_provider_id IS NULL GROUP BY p.id ORDER BY p.name""")
        return render_template("providers.html", title="Providers", providers=providers)

    @app.get("/providers/<int:provider_id>")
    def provider_detail(provider_id):
        provider = db().execute("SELECT * FROM providers WHERE id=?", (provider_id,)).fetchone()
        if not provider:
            abort(404)
        return redirect(url_for("provider_detail_slug", provider_slug=slugify(provider["name"])), code=301)

    @app.get("/providers/<provider_slug>")
    def provider_detail_slug(provider_slug):
        provider = next((p for p in rows("SELECT * FROM providers") if slugify(p["name"]) == provider_slug), None)
        if not provider:
            abort(404)
        provider_id = provider["id"]
        routes = route_rows(db(), {"provider_id": provider_id, "limit": 48})
        protocol_capabilities = rows("""SELECT ppe.*,p.name endpoint_provider,s.name source_name,s.url source_url
          FROM provider_protocol_evidence ppe JOIN providers p ON p.id=ppe.provider_id
          JOIN sources s ON s.id=ppe.source_id
          WHERE ppe.provider_id IN (SELECT id FROM providers WHERE id=? OR canonical_provider_id=?)
          ORDER BY p.name,ppe.protocol""", (provider_id, provider_id))
        route_count = db().execute("""SELECT COUNT(*) FROM provider_offerings WHERE lifecycle_status!='REMOVED'
          AND provider_id IN (SELECT id FROM providers WHERE id=? OR canonical_provider_id=?)""", (provider_id, provider_id)).fetchone()[0]
        sources = rows("""SELECT DISTINCT s.name,s.url,s.reliability,s.fetched_at FROM sources s WHERE s.id IN (
          SELECT source_id FROM provider_offerings WHERE provider_id IN (SELECT id FROM providers WHERE id=? OR canonical_provider_id=?)
          UNION SELECT source_id FROM plans WHERE provider_id IN (SELECT id FROM providers WHERE id=? OR canonical_provider_id=?)
          UNION SELECT source_id FROM offers WHERE provider_id IN (SELECT id FROM providers WHERE id=? OR canonical_provider_id=?)
          UNION SELECT source_id FROM provider_protocol_evidence WHERE provider_id IN (SELECT id FROM providers WHERE id=? OR canonical_provider_id=?))
          ORDER BY s.reliability,s.name""", (provider_id, provider_id, provider_id, provider_id,
                                                provider_id, provider_id, provider_id, provider_id))
        verified = max([r["fetched_at"] for r in routes if r["fetched_at"]] + [s["fetched_at"] for s in sources if s["fetched_at"]], default=None)
        canonical = absolute_url(url_for('provider_detail_slug', provider_slug=provider_slug))
        schema = {"@context": "https://schema.org", "@type": "Dataset", "name": f"{provider['name']} AI model route catalog", "description": f"Source-backed prices, capabilities, offers and limits for {provider['name']} routes.", "url": canonical, "dateModified": verified[:10] if verified else None}
        return render_template("provider_detail.html", title=f"{provider['name']} AI models, pricing & routes", provider=provider, routes=routes, route_count=route_count, protocol_capabilities=protocol_capabilities, plans=rows("SELECT * FROM plans WHERE provider_id IN (SELECT id FROM providers WHERE id=? OR canonical_provider_id=?)", (provider_id, provider_id)), offers=rows("SELECT * FROM offers WHERE provider_id IN (SELECT id FROM providers WHERE id=? OR canonical_provider_id=?) ORDER BY status,ends_at", (provider_id, provider_id)), sources=sources, last_verified_at=verified, canonical_url=canonical, structured_data=schema, meta_description=f"Documented {provider['name']} AI model routes, current prices, limits, offers, sources, and last verification dates.")

    @app.get("/harnesses")
    def harnesses():
        return render_template("harnesses.html", title="Harnesses", harnesses=rows("SELECT * FROM harnesses ORDER BY name"))

    @app.get("/harnesses/<int:harness_id>")
    def harness_detail(harness_id):
        harness = db().execute("SELECT * FROM harnesses WHERE id=?", (harness_id,)).fetchone()
        if not harness:
            abort(404)
        return redirect(url_for("harness_detail_slug", harness_slug=slugify(harness["name"])), code=301)

    @app.get("/harnesses/<harness_slug>")
    def harness_detail_slug(harness_slug):
        requested_slug = {"codex": "codex-cli", "hermes": "hermes-agent"}.get(harness_slug, harness_slug)
        harness = next((h for h in rows("SELECT * FROM harnesses") if slugify(h["name"]) == requested_slug), None)
        if not harness:
            abort(404)
        harness_id = harness["id"]
        capabilities = rows("SELECT transport,state,note FROM harness_mcp_capabilities WHERE harness_id=?", (harness_id,))
        claims = rows("""SELECT hc.*,s.name source_name,s.url source_url FROM harness_claims hc
          JOIN sources s ON s.id=hc.source_id WHERE hc.harness_id=? ORDER BY hc.claim_key""", (harness_id,))
        access_methods = rows("""SELECT ha.*,s.name source_name,s.url source_url FROM harness_access_methods ha
          JOIN sources s ON s.id=ha.source_id WHERE ha.harness_id=? ORDER BY ha.access_method""", (harness_id,))
        protocols = rows("""SELECT hps.*,s.name source_name,s.url source_url
          FROM harness_protocol_support hps JOIN sources s ON s.id=hps.source_id
          WHERE hps.harness_id=? ORDER BY hps.protocol,hps.access_method""", (harness_id,))
        routes = [{**route, "compatibility": route["_compatibility"]}
                  for route in compatible_route_rows(db(), {}, harness_id)]
        sources = rows("""SELECT DISTINCT s.name,s.url,s.reliability,s.fetched_at FROM sources s WHERE s.id IN (
          SELECT source_id FROM harnesses WHERE id=? UNION SELECT source_id FROM harness_mcp_capabilities WHERE harness_id=?
          UNION SELECT source_id FROM harness_provider_compatibility WHERE harness_id=?
          UNION SELECT source_id FROM harness_protocol_support WHERE harness_id=?) ORDER BY s.name""",
          (harness_id, harness_id, harness_id, harness_id))
        verified = max([s["fetched_at"] for s in sources if s["fetched_at"]], default=None)
        routes.sort(key=lambda route: (
            not bool(route["compatibility"].get("source")),
            route.get("input_price") is None,
            route.get("input_price") or 0,
            route.get("canonical_name", ""),
            route.get("provider_name", ""),
        ))
        canonical_slug = next((alias for alias, target in {"codex": "codex-cli", "hermes": "hermes-agent"}.items()
                               if target == requested_slug), requested_slug)
        canonical = absolute_url(url_for('harness_detail_slug', harness_slug=canonical_slug))
        schema = {"@context": "https://schema.org", "@type": "SoftwareApplication", "name": harness["name"], "applicationCategory": "DeveloperApplication", "operatingSystem": harness["supported_os"], "url": canonical, "softwareVersion": harness["current_version"]}
        return render_template("harness_detail.html", title=f"{harness['name']} providers, models & MCP compatibility", item=dict(harness), capabilities=capabilities, claims=claims, access_methods=access_methods, protocols=protocols, routes=routes[:24], sources=sources, last_verified_at=verified, canonical_url=canonical, structured_data=schema, meta_description=f"Documented {harness['name']} provider integrations, model-route compatibility, MCP capabilities, sources, and caveats.")

    @app.get("/workflows")
    def workflows():
        return render_template("workflows.html", title="Workflow and tool integrations", workflows=rows("""SELECT w.*,
          COUNT(wi.id) integration_count FROM workflows w LEFT JOIN workflow_integrations wi ON wi.workflow_id=w.id
          GROUP BY w.id ORDER BY w.name"""))

    @app.get("/workflows/<workflow_slug>")
    def workflow_detail(workflow_slug):
        workflow = db().execute("SELECT * FROM workflows WHERE slug=?", (workflow_slug,)).fetchone()
        if not workflow:
            abort(404)
        integrations = rows("""SELECT wi.*,s.name source_name,s.url source_url FROM workflow_integrations wi
          JOIN sources s ON s.id=wi.source_id WHERE wi.workflow_id=? ORDER BY wi.maintenance_status='ACTIVE' DESC,wi.name""", (workflow["id"],))
        hosts = rows("""SELECT h.name harness_name,wi.name integration_name,whc.state,whc.reason,
          s.url source_url,whc.verified_at FROM workflow_harness_compatibility whc
          JOIN workflow_integrations wi ON wi.id=whc.integration_id JOIN harnesses h ON h.id=whc.harness_id
          JOIN sources s ON s.id=whc.source_id WHERE wi.workflow_id=? ORDER BY h.name,wi.name""", (workflow["id"],))
        route_matches = rows("""SELECT rce.*,h.name harness_name,o.id offering_id,o.api_model_id,
          m.canonical_name,m.canonical_slug,p.name provider_name,o.context_limit,o.access_semantics,o.access_requirement,o.tool_support,
          (SELECT amount FROM pricing_records pr WHERE pr.offering_id=o.id AND pr.price_type='INPUT' AND pr.valid_until IS NULL ORDER BY pr.valid_from DESC LIMIT 1) input_price,
          (SELECT amount FROM pricing_records pr WHERE pr.offering_id=o.id AND pr.price_type='OUTPUT' AND pr.valid_until IS NULL ORDER BY pr.valid_from DESC LIMIT 1) output_price,
          s.url source_url FROM route_compatibility_evidence rce JOIN harnesses h ON h.id=rce.harness_id
          JOIN provider_offerings o ON o.id=rce.offering_id JOIN models m ON m.id=o.model_id
          JOIN providers p ON p.id=o.provider_id JOIN sources s ON s.id=rce.source_id
          WHERE h.id IN (SELECT whc.harness_id FROM workflow_harness_compatibility whc
            JOIN workflow_integrations wi ON wi.id=whc.integration_id WHERE wi.workflow_id=?)
          ORDER BY o.free_status='FREE' DESC,COALESCE(input_price,999999),m.canonical_name""", (workflow["id"],))
        benchmarks = rows("""SELECT b.name,b.version,b.category,br.score,br.metric,m.canonical_name,
          br.task_subset,br.harness_name,br.scaffold,br.reasoning_setting,br.evaluated_at,
          br.confidence,s.url source_url FROM benchmark_results br JOIN benchmarks b ON b.id=br.benchmark_id
          JOIN models m ON m.id=br.model_id LEFT JOIN sources s ON s.id=br.source_id
          WHERE lower(b.category) LIKE '%cod%' AND b.is_current=1
          ORDER BY b.name,b.version,br.metric,br.task_subset,br.harness_name,br.scaffold,br.evaluated_at DESC LIMIT 100""")
        schema = {"@context": "https://schema.org", "@type": "Dataset", "name": f"{workflow['name']} compatibility routes", "description": workflow["description"], "url": absolute_url(request.path), "dateModified": workflow["verified_at"]}
        return render_template("workflow_detail.html", title=f"{workflow['name']} compatibility", workflow=workflow,
          integrations=integrations, hosts=hosts, route_matches=route_matches, benchmarks=benchmarks,
          structured_data=schema,
          canonical_url=absolute_url(request.path),
          meta_description=f"Source-backed {workflow['name']} MCP servers, compatible harness hosts, model routes, prices, and evidence.")

    @app.get("/compatibility")
    def compatibility():
        filters, interpreted = interpreted_filters()
        matches = compatible_routes({**filters, "limit": 13}) if filters.get("harness") else []
        return render_template("compatibility.html", title="Compatibility finder", filters=filters, interpreted=interpreted, options=filter_options(db()), routes=matches[:12], has_more=len(matches) > 12)

    @app.get("/compare")
    def compare():
        raw_ids = request.args.getlist("ids")
        ids = [int(value) for raw in raw_ids for value in raw.split(",") if value.isdigit()][:5]
        compare_query = request.args.get("q", "").strip()
        query_parts = [part.strip() for part in re.split(r"\s+(?:vs\.?|versus|with)\s+|,", compare_query, flags=re.I) if part.strip()]
        all_routes = []
        for part in query_parts or [""]:
            all_routes.extend(route_rows(db(), {"q": part, "limit": 20, "sort": "featured"}))
        all_routes = list({route["offering_id"]: route for route in all_routes}.values())[:40]
        selected = []
        for offering_id in ids:
            route = next(iter(route_rows(db(), {"offering_id": offering_id})), None)
            if route:
                selected.append(route)
        histories = {r["offering_id"]: price_history(db(), r["offering_id"]) for r in selected}
        for items in histories.values():
            for item in items:
                item["chart"] = price_history_chart(item["records"])
        price_deltas = {}
        for field in ("input_price", "output_price"):
            available = [route[field] for route in selected if route.get(field) is not None]
            baseline = min(available) if available else None
            for route in selected:
                amount = route.get(field)
                price_deltas.setdefault(route["offering_id"], {})[field] = (
                    round(amount - baseline, 6) if amount is not None and baseline is not None else None
                )
        from .benchmark_queries import comparable_groups
        model_ids = sorted({route["model_id"] for route in selected})
        marks = ",".join("?" for _ in model_ids) or "NULL"
        evidence = rows(f"""SELECT b.id benchmark_id,b.name benchmark,b.version,b.is_current,
          br.model_id,m.canonical_name model,br.score,br.metric,br.task_subset,br.harness_name,
          br.harness_version,br.scaffold,br.reasoning_setting,br.tool_policy,br.network_policy,
          br.step_budget,br.token_budget,br.time_budget_seconds,br.attempts_per_task,br.grader_version,
          br.evaluated_at,br.confidence,br.confidence_interval,s.url source_url
          FROM benchmark_results br JOIN benchmarks b ON b.id=br.benchmark_id
          JOIN models m ON m.id=br.model_id LEFT JOIN sources s ON s.id=br.source_id
          WHERE br.model_id IN ({marks}) AND b.is_current=1""", model_ids)
        benchmark_groups = comparable_groups(evidence)
        return render_template("compare.html", title="Compare routes", routes=selected,
                               all_routes=all_routes, histories=histories, compare_query=compare_query,
                               benchmark_groups=benchmark_groups, price_deltas=price_deltas)

    @app.get("/plans")
    def plans():
        filters = finder_filters()
        routes_by_family = {}
        for route in access_route_rows(db()):
            routes_by_family.setdefault(route["model_family"], []).append(route)
        providers = rows("""SELECT DISTINCT p.name FROM plans pl JOIN providers p ON p.id=pl.provider_id
          WHERE pl.status IN ('ACTIVE','LIMITED','WAITLIST') ORDER BY p.name""")
        harnesses = rows("""SELECT DISTINCT h.name FROM plan_harness_compatibility ph
          JOIN harnesses h ON h.id=ph.harness_id ORDER BY h.name""")
        return render_template(
            "plans.html", title="Developer plans & access routes", plans=plan_rows(db(), filters),
            filters=filters, plan_providers=providers, plan_harnesses=harnesses,
            routes_by_family=routes_by_family,
            canonical_url=absolute_url(request.path),
            meta_description="Compare current AI coding subscriptions, explicit allowances, API separation, harness compatibility, and model access routes from official sources.",
        )

    @app.get("/calculator")
    def calculator():
        filters = finder_filters()
        def bounded_int(name, default, maximum=10_000_000_000):
            try:
                return min(maximum, max(0, int(request.args.get(name, default) or 0)))
            except (TypeError, ValueError):
                return default
        input_tokens = bounded_int("input_tokens", 1_000_000)
        output_tokens = bounded_int("output_tokens", 250_000)
        cache_share = min(100, bounded_int("cache_share", 0, 100)) / 100
        cache_write_share = min(100-cache_share*100, bounded_int("cache_write_share", 0, 100)) / 100
        batch = request.args.get("batch") == "1"
        selected_plan = None
        if request.args.get("plan_id", "").isdigit():
            selected_plan = db().execute("""SELECT pl.*,p.name provider_name,s.url source_url
              FROM plans pl JOIN providers p ON p.id=pl.provider_id LEFT JOIN sources s ON s.id=pl.source_id
              WHERE pl.id=?""", (int(request.args["plan_id"]),)).fetchone()
        calculated = []
        for route in compatible_routes(filters):
            from .costing import estimate_token_cost
            price_rows = db().execute("SELECT price_type,amount,unit,context_threshold FROM pricing_records WHERE offering_id=? AND valid_until IS NULL", (route["offering_id"],)).fetchall()
            prices = {}
            for price_row in price_rows:
                price = prices.setdefault(price_row["price_type"], {"amount": price_row["amount"], "unit": price_row["unit"]})
                if price_row["context_threshold"] is not None:
                    price["tiered"] = True
            usage = {"input": round(input_tokens * (1-cache_share-cache_write_share)), "output": output_tokens,
                     "cache_read": round(input_tokens * cache_share),
                     "cache_write": round(input_tokens * cache_write_share)}
            estimate = estimate_token_cost(prices, usage, batch=batch)
            if estimate["cost"] is None:
                continue
            calculated.append({**route, "monthly_cost": estimate["cost"], "batch_applied": bool(estimate["batch_classes_used"])})
        calculated = sorted(calculated, key=lambda r: r["monthly_cost"])
        return render_template("calculator.html", title="Cost calculator", filters=filters, options=filter_options(db()), routes=calculated[:12], route_count=len(calculated), plans=plan_rows(db(), {"subscription": "1", "coding": "1"}), selected_plan=dict(selected_plan) if selected_plan else None, input_tokens=input_tokens, output_tokens=output_tokens, cache_share=round(cache_share*100), cache_write_share=round(cache_write_share*100), batch=batch)

    @app.get("/deals")
    def offers():
        differences = pricing_differences(db())
        current_offers = offer_rows(db())
        free_routes = openrouter_free_rows(db())
        provider_filter = request.args.get("provider", "").strip()
        model_filter = request.args.get("model", "").strip()
        kind_filter = request.args.get("kind", "").strip()
        tools_filter = request.args.get("tools", "").strip()
        harness_filter = request.args.get("harness", "").strip()
        context_filter = request.args.get("context", "").strip()
        filtered = current_offers
        if provider_filter:
            filtered = [o for o in filtered if provider_filter.casefold() in o["provider_name"].casefold()]
        if model_filter:
            filtered = [o for o in filtered if model_filter.casefold() in (o.get("canonical_name") or "").casefold()]
        if kind_filter == "free":
            filtered = [o for o in filtered if o["offer_type"] == "$0_ROUTE"]
        elif kind_filter == "discount":
            filtered = [o for o in filtered if o.get("discount_percent")]
        if request.args.get("subscription") == "1":
            filtered = [o for o in filtered if o.get("access_semantics") == "INCLUDED_WITH_SUBSCRIPTION"]
        if tools_filter == "1":
            filtered = [o for o in filtered if o.get("tool_support") == "YES"]
        if context_filter:
            try:
                minimum_context = int(normalize_context(context_filter))
                filtered = [o for o in filtered if (o.get("context_limit") or 0) >= minimum_context]
            except ValueError:
                filtered = []
        if harness_filter:
            harness = db().execute("SELECT id FROM harnesses WHERE lower(name)=lower(?) OR lower(replace(name,' ', '-'))=lower(?)", (harness_filter, harness_filter)).fetchone()
            if not harness:
                filtered = []
            else:
                filtered = [o for o in filtered if o.get("offering_id") and compatibility_for(db(), harness["id"], o["offering_id"])['status'] in {"COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION", "PARTIAL"}]
        try:
            offer_page = max(1, int(request.args.get("page", "1")))
        except ValueError:
            offer_page = 1
        offer_size = 20
        offer_page_params = request.args.to_dict()
        offer_page_params.pop("page", None)
        offer_prev_url = "/deals?" + urlencode({**offer_page_params, "page": offer_page-1}) if offer_page > 1 else None
        offer_next_url = "/deals?" + urlencode({**offer_page_params, "page": offer_page+1}) if offer_page*offer_size < len(filtered) else None
        canonical = absolute_url("/deals")
        schema = {"@context": "https://schema.org", "@type": "ItemList", "name": "Current AI model deals",
                  "url": canonical, "itemListElement": [
                      {"@type": "Offer", "name": offer["title"], "url": offer["terms_url"] or canonical,
                       "validThrough": offer["ends_at"], "availability": "https://schema.org/InStock"}
                      for offer in current_offers[:8]]}
        return render_template("offers.html", title="Offers & deals", offers=filtered[(offer_page-1)*offer_size:offer_page*offer_size],
          offer_count=len(filtered), all_offer_count=len(current_offers), offer_page=offer_page,
          offer_has_more=offer_page*offer_size < len(filtered), offer_filters=request.args,
          offer_prev_url=offer_prev_url, offer_next_url=offer_next_url,
          offer_providers=sorted({o["provider_name"] for o in current_offers}), offer_harnesses=rows("SELECT id,name FROM harnesses ORDER BY name"),
          expired=offer_rows(db(), include_expired=True),
          free_routes=free_routes[:8], free_count=len(free_routes),
          discounts=differences["discounts"][:8], direct_differences=differences["direct"][:8],
          structured_data=schema, canonical_url=canonical,
          meta_description="Current source-backed AI model deals, free routes, discounts, terms, expiration dates, and last verification dates.")

    @app.get("/offers")
    def offers_legacy():
        return redirect(url_for("offers"), code=301)

    @app.get("/rankings")
    def rankings():
        harness_rankings = rows("""SELECT *, CASE open_source WHEN 'YES' THEN 1 ELSE 0 END open_source_value,
          CASE supports_mcp WHEN 1 THEN 1 ELSE 0 END mcp_value
          FROM harnesses ORDER BY mcp_value DESC,open_source_value DESC,name""")
        return render_template("rankings.html", title="Factual rankings", groups=ranking_groups(db()), harnesses=harness_rankings)

    @app.get("/my-setup")
    def my_setup():
        selected_harnesses = request.args.getlist("harnesses")
        selected_workflows = request.args.getlist("workflows")
        setup_routes = []
        if selected_harnesses or selected_workflows:
            base_filters = {"tools": "1", "sort": "weighted_cost", "limit": 500}
            if "coding" in selected_workflows:
                base_filters["use_case"] = "coding"
            candidates = route_rows(db(), base_filters)
            harness_rows = [db().execute("SELECT id,name FROM harnesses WHERE name=?", (name,)).fetchone()
                            for name in selected_harnesses]
            workflow_rows = [db().execute("SELECT id,name FROM workflows WHERE slug=?", (slug,)).fetchone()
                             for slug in selected_workflows if slug != "coding"]
            allowed = {"COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION", "PARTIAL"}
            workflow_hosts = {workflow["id"]: db().execute("""SELECT DISTINCT h.id,h.name
              FROM workflow_harness_compatibility whc
              JOIN workflow_integrations wi ON wi.id=whc.integration_id
              JOIN harnesses h ON h.id=whc.harness_id
              WHERE wi.workflow_id=? AND whc.state IN ('YES','CONFIGURATION','PARTIAL')""",
              (workflow["id"],)).fetchall() for workflow in workflow_rows if workflow}
            for route in candidates:
                checks = []
                for harness in [h for h in harness_rows if h]:
                    if workflow_rows:
                        checks.extend(compatibility_for(db(), harness["id"], route["offering_id"], True, workflow["id"])
                                      for workflow in workflow_rows if workflow)
                    else:
                        checks.append(compatibility_for(db(), harness["id"], route["offering_id"], False))
                workflow_only_groups = []
                if not selected_harnesses and workflow_rows:
                    workflow_only_groups = [[compatibility_for(
                        db(), host["id"], route["offering_id"], True, workflow["id"]
                    ) for host in workflow_hosts.get(workflow["id"], [])] for workflow in workflow_rows]
                    checks = [check for group in workflow_only_groups for check in group]
                qualifies = (
                    not selected_harnesses and not workflow_rows
                    or workflow_only_groups and all(any(check["status"] in allowed for check in group)
                                                    for group in workflow_only_groups)
                    or selected_harnesses and checks and all(check["status"] in allowed for check in checks)
                )
                if qualifies:
                    compatible_check = next((check for check in checks if check["status"] in allowed), None)
                    if compatible_check:
                        route["compatibility"] = compatible_check
                    setup_routes.append(route)
                if len(setup_routes) == 6:
                    break
        return render_template("my_setup.html", title="My Setup",
          harnesses=rows("SELECT id,name,interfaces,open_source,supports_mcp FROM harnesses ORDER BY name"),
          setup_routes=setup_routes, selected_harnesses=selected_harnesses,
          selected_workflows=selected_workflows)

    @app.get("/releases")
    def releases():
        try:
            release_page = max(1, int(request.args.get("page", "1")))
        except ValueError:
            release_page = 1
        release_page_size = 50
        release_count = db().execute("SELECT COUNT(*) FROM models WHERE released_at IS NOT NULL AND status!='DEPRECATED'").fetchone()[0]
        release_models = rows("""SELECT m.*,l.name lab_name,
          (SELECT COUNT(*) FROM provider_offerings o WHERE o.model_id=m.id) route_count,
          (SELECT o.tool_support FROM provider_offerings o WHERE o.model_id=m.id
             ORDER BY CASE o.tool_support WHEN 'YES' THEN 0 WHEN 'UNKNOWN' THEN 1 ELSE 2 END LIMIT 1) tool_support,
          (SELECT s.name FROM data_observations d JOIN sources s ON s.id=d.source_id
             WHERE d.entity='model:'||m.id AND d.field IN ('released_at','release_date') ORDER BY d.id DESC LIMIT 1) release_source_name,
          (SELECT s.url FROM data_observations d JOIN sources s ON s.id=d.source_id
             WHERE d.entity='model:'||m.id AND d.field IN ('released_at','release_date') ORDER BY d.id DESC LIMIT 1) release_source_url
          FROM models m LEFT JOIN labs l ON l.id=m.lab_id
          WHERE m.released_at IS NOT NULL AND m.status!='DEPRECATED'
          ORDER BY m.released_at DESC,m.canonical_name LIMIT ? OFFSET ?""",
          (release_page_size, (release_page-1)*release_page_size))
        release_models = [dict(item) for item in release_models]
        groups = []
        for item in release_models:
            item["release_source"] = ({"name": item["release_source_name"], "url": item["release_source_url"]}
                                      if item["release_source_url"] else None)
            item["release_confidence"] = {"official":"Official", "publisher_metadata":"Publisher metadata", "aggregator":"Aggregator"}.get(item["release_date_kind"], "Unverified")
            item["category"] = modality_category(item["modality"], item["canonical_name"])
            item["group"] = item["released_at"][:7]
            if item["group"] not in groups:
                groups.append(item["group"])
        canonical = absolute_url("/releases")
        schema = {"@context": "https://schema.org", "@type": "Dataset", "name": "New AI model releases",
                  "description": "Recently released models with current provider routes, prices, capabilities and source verification.", "url": canonical}
        return render_template("releases.html", title="New releases", release_models=release_models,
          groups=groups, release_count=release_count, release_page=release_page,
          release_prev_url=f"/releases?page={release_page-1}" if release_page > 1 else None,
          release_next_url=f"/releases?page={release_page+1}" if release_page*release_page_size < release_count else None,
          structured_data=schema,
          canonical_url=canonical, meta_description="Chronological AI model releases with date provenance, capabilities, and exact provider route counts.")

    @app.get("/new-releases")
    def legacy_releases():
        return redirect(url_for("releases"), code=301)

    @app.get("/benchmarks")
    def benchmarks():
        return render_template("benchmarks.html", title="Benchmarks", benchmarks=rows("SELECT b.*,COUNT(br.id) result_count FROM benchmarks b LEFT JOIN benchmark_results br ON br.benchmark_id=b.id GROUP BY b.id ORDER BY b.is_current DESC,b.name,b.version DESC"), results=rows("""SELECT b.name benchmark,b.version,m.canonical_name,m.canonical_slug,
          br.score,br.metric,br.task_subset,br.confidence,br.harness_name,br.harness_version,
          br.scaffold,br.reasoning_setting,br.evaluated_at,s.url source_url
          FROM benchmark_results br JOIN benchmarks b ON b.id=br.benchmark_id
          JOIN models m ON m.id=br.model_id LEFT JOIN sources s ON s.id=br.source_id
          WHERE b.is_current=1 AND br.confidence IN ('HIGH','MEDIUM')
          ORDER BY b.name,b.version,br.metric,br.task_subset,br.harness_name,br.harness_version,
            br.scaffold,br.reasoning_setting,br.tool_policy,br.network_policy,br.attempts_per_task,
            br.grader_version,br.score DESC"""))

    @app.get("/use-cases")
    def use_cases():
        return render_template("use_cases.html", title="Use cases", use_cases=filter_options(db())["use_cases"])

    @app.get("/benchmarks/<benchmark_slug>")
    def benchmark_detail(benchmark_slug):
        benchmark = next((b for b in rows("SELECT * FROM benchmarks") if slugify(f"{b['name']}-{b['version']}") == benchmark_slug), None)
        if not benchmark:
            abort(404)
        results = rows("""SELECT m.canonical_name,m.canonical_slug,br.*,s.name source_name,s.url source_url
          FROM benchmark_results br JOIN models m ON m.id=br.model_id LEFT JOIN sources s ON s.id=br.source_id
          WHERE br.benchmark_id=? ORDER BY br.metric,br.task_subset,br.harness_name,br.harness_version,
            br.scaffold,br.reasoning_setting,br.tool_policy,br.network_policy,br.attempts_per_task,
            br.grader_version,br.score DESC""", (benchmark["id"],))
        source = db().execute("SELECT * FROM sources WHERE id=?", (benchmark["source_id"],)).fetchone() if benchmark["source_id"] else None
        versions = rows("SELECT name,version,is_current,published_at FROM benchmarks WHERE name=? ORDER BY published_at DESC,version DESC", (benchmark["name"],))
        return render_template("benchmark_detail.html", title=f"{benchmark['name']} {benchmark['version']} benchmark", benchmark=benchmark, results=results, source=source, versions=versions, canonical_url=absolute_url(request.path), meta_description=f"{benchmark['name']} {benchmark['version']} methodology, metric-specific results, harness details, sources, and caveats.")

    @app.get("/internal/data-quality")
    def internal_data_quality():
        require_internal_access()
        from .data_quality import data_quality_metrics, review_triage, source_health_rows
        return render_template(
            "data_quality.html",
            title="Internal data quality",
            metrics=data_quality_metrics(db()),
            triage=review_triage(db()),
            source_health=source_health_rows(db()),
            robots_meta="noindex,nofollow",
        )

    @app.get("/internal/analytics")
    def internal_analytics():
        require_internal_access()
        analytics = rows("""SELECT day,event,dimension,count FROM analytics_daily
          WHERE day>=date('now','-30 days') ORDER BY day DESC,count DESC,event,dimension""")
        return render_template("analytics.html", title="Private aggregate analytics", analytics=analytics,
                               robots_meta="noindex,nofollow")

    @app.get("/use-cases/<use_case_slug>")
    def use_case_detail(use_case_slug):
        aliases = {"free-tool-calling": "tool-calling", "3d-generation": "3d"}
        data_slug = aliases.get(use_case_slug, use_case_slug)
        use_case = db().execute("SELECT * FROM use_cases WHERE slug=?", (data_slug,)).fetchone()
        if not use_case:
            abort(404)
        scores = rows("""SELECT m.canonical_name,m.canonical_slug,mus.classification,mus.confidence,mus.rationale,
          s.name source_name,s.url source_url,s.fetched_at FROM model_use_case_scores mus JOIN models m ON m.id=mus.model_id
          LEFT JOIN sources s ON s.id=mus.source_id WHERE mus.use_case_id=?
          ORDER BY CASE mus.classification WHEN 'RECOMMENDED' THEN 0 WHEN 'SUPPORTED' THEN 1 ELSE 2 END,m.canonical_name""", (use_case["id"],))
        route_filter = ({"free": "1", "tools": "1"} if use_case_slug == "free-tool-calling"
                        else {"type": "3D generation"} if use_case_slug == "3d-generation"
                        else {"use_case": data_slug})
        matching_routes = route_rows(db(), {**route_filter, "limit": 12})
        model_ids = [row["model_id"] for row in matching_routes]
        marks = ",".join("?" for _ in model_ids) or "NULL"
        relevant_benchmarks = rows(f"""SELECT b.name,b.version,br.score,br.metric,m.canonical_name,m.canonical_slug,
          br.task_subset,br.harness_name,br.scaffold,br.reasoning_setting,br.evaluated_at,br.confidence,s.url source_url
          FROM benchmark_results br JOIN benchmarks b ON b.id=br.benchmark_id JOIN models m ON m.id=br.model_id
          LEFT JOIN sources s ON s.id=br.source_id WHERE br.model_id IN ({marks}) AND b.is_current=1
          ORDER BY b.name,b.version,br.metric,br.task_subset,br.harness_name,br.scaffold,br.evaluated_at DESC LIMIT 100""", model_ids)
        deal_rows = [offer for offer in offer_rows(db()) if offer.get("offering_id") in {route["offering_id"] for route in matching_routes}][:6]
        verified = max([row["fetched_at"] for row in scores if row["fetched_at"]] + [row["fetched_at"] for row in matching_routes if row["fetched_at"]], default=None)
        canonical_path = "3d-generation" if data_slug == "3d" else use_case_slug
        canonical = absolute_url(url_for('use_case_detail', use_case_slug=canonical_path))
        schema = {"@context": "https://schema.org", "@type": "Dataset", "name": f"AI model routes for {use_case['name']}", "description": use_case["description"], "url": canonical, "dateModified": verified[:10] if verified else None}
        return render_template("use_case_detail.html", title=f"AI models for {use_case['name']}", use_case=use_case, scores=scores, routes=matching_routes, offers=deal_rows, benchmarks=relevant_benchmarks, last_verified_at=verified, structured_data=schema, canonical_url=canonical, meta_description=f"Source-backed AI model routes for {use_case['name']}, with classifications, prices, capabilities, compatibility, deals, benchmarks, and verification dates.")

    return app

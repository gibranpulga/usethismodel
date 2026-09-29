import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, abort, g, jsonify, redirect, render_template, request, url_for

from .db import init_db
from .domain import compatibility_for
from .public import public, slugify
from .query import (
    access_route_rows,
    filter_options,
    interpret_search,
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
       ("Compare", "/compare"), ("Offers", "/offers"), ("Calculator", "/calculator")]
MORE_NAV = [("Compatibility", "/compatibility"), ("Plans", "/plans"),
            ("New Releases", "/new-releases"), ("Harnesses", "/harnesses"),
            ("Workflows", "/workflows"), ("Benchmarks", "/benchmarks"),
            ("Providers", "/providers"), ("Use Cases", "/use-cases"),
            ("Rankings", "/rankings"), ("MCP", "/mcp-info")]
PRESETS = {
    "free-tools": ("Free + Tools", {"free": "1", "tools": "1"}), "cheap-agent": ("Cheapest Agent Models", {"tools": "1", "use_case": "agentic-coding"}),
    "strong-coding": ("Strong Coding", {"tools": "1", "use_case": "coding"}), "best-value-coding": ("Best Value Coding", {"tools": "1", "use_case": "coding", "sort": "value"}),
    "million-tools": ("1M Context + Tools", {"context": "1000000", "tools": "1"}), "open-tools": ("Open Weight + Tools", {"open_weights": "1", "tools": "1"}),
    "new-week": ("New This Week", {"release": "week"}), "discounts": ("Current Discounts", {"deal": "1"}), "hermes": ("Works With Hermes", {"harness": "Hermes Agent"}),
    "opencode": ("Works With OpenCode", {"harness": "OpenCode"}), "pi": ("Works With Pi", {"harness": "Pi"}), "codex": ("Works With Codex", {"harness": "Codex CLI"}),
}


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(SECRET_KEY=os.getenv("FLASK_SECRET_KEY", "local-development-key"), DATABASE=os.getenv("DATABASE_PATH", str(Path(app.instance_path) / "usethismodel.sqlite3")))
    if test_config:
        app.config.update(test_config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    init_db(app)
    app.register_blueprint(public)
    app.jinja_env.globals["slugify"] = slugify

    @app.before_request
    def content_security_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)
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
        return response

    @app.context_processor
    def navigation():
        from .data_quality import freshness_text
        canonical = request.url_root.rstrip("/") + request.path
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
        }

    def db():
        from .db import get_db
        return get_db()

    def rows(query, params=()):
        return db().execute(query, params).fetchall()

    def finder_filters():
        return {key: value for key, value in request.args.items() if value not in ("", "any", None)}

    def interpreted_filters():
        return interpret_search(finder_filters())

    def compatible_routes(filters):
        harness_names = [name for name in filters.get("harnesses", "").split(",") if name]
        if filters.get("harness"):
            harness_names.insert(0, filters["harness"])
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
                return []
            if not harness_names:
                workflow_only = True
                harness_names = [row["name"] for row in db().execute("""SELECT DISTINCT h.name
                  FROM workflow_harness_compatibility whc
                  JOIN workflow_integrations wi ON wi.id=whc.integration_id
                  JOIN harnesses h ON h.id=whc.harness_id
                  WHERE wi.workflow_id=? AND whc.state IN ('YES','CONFIGURATION','PARTIAL')""",
                  (workflow["id"],)).fetchall()]
        route_filters = {key: value for key, value in filters.items() if key != "workflow"}
        candidate_limit = min(1_000, max(250, requested_offset + requested_limit * 20))
        query_filters = ({**route_filters, "limit": candidate_limit, "offset": 0}
                         if harness_names else route_filters)
        result = route_rows(db(), query_filters)
        if not harness_names:
            return result
        harnesses = [db().execute("SELECT id,name FROM harnesses WHERE name=?", (name,)).fetchone() for name in harness_names]
        if any(not harness for harness in harnesses):
            return []
        kept = []
        for route in result:
            matches = [(harness["name"], compatibility_for(
                db(), harness["id"], route["offering_id"],
                filters.get("mcp") == "1" or workflow is not None,
                workflow["id"] if workflow else None,
            )) for harness in harnesses]
            allowed = {"COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION", "PARTIAL"}
            qualifies = (any(match["status"] in allowed for _, match in matches)
                         if workflow_only else all(match["status"] in allowed for _, match in matches))
            if qualifies:
                match = next(value for _, value in matches if value["status"] in allowed)
                if len(matches) > 1 and not workflow_only:
                    match = {**match, "explanation": " ".join(f"{name}: {value['explanation']}" for name, value in matches)}
                route["compatibility"] = match
                kept.append(route)
                if len(kept) >= requested_offset + requested_limit:
                    break
        return kept[requested_offset:requested_offset + requested_limit]

    @app.get("/health")
    def health():
        db().execute("SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1").fetchone()
        return jsonify(status="ok", database="sqlite")

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
        latest = route_rows(db(), {"release": "week", "sort": "newest", "limit": 3})
        popular = rows("""SELECT m.id,m.canonical_name,m.canonical_slug,COUNT(o.id) route_count
          FROM models m JOIN provider_offerings o ON o.model_id=m.id GROUP BY m.id
          ORDER BY route_count DESC,m.canonical_name LIMIT 3""")
        changes = rows("""SELECT o.id offering_id,m.canonical_name,p.name provider_name,pr.price_type,
          pr.amount,pr.unit,pr.valid_from FROM pricing_records pr
          JOIN provider_offerings o ON o.id=pr.offering_id JOIN models m ON m.id=o.model_id
          JOIN providers p ON p.id=o.provider_id WHERE pr.valid_until IS NULL AND EXISTS(
            SELECT 1 FROM pricing_records old WHERE old.offering_id=pr.offering_id
            AND old.price_type=pr.price_type AND old.id!=pr.id)
          ORDER BY pr.valid_from DESC LIMIT 6""")
        return render_template(
            "index.html", title="AI model, provider route & harness finder", filters=filters,
            interpreted=interpreted, options=filter_options(db()), routes=compatible_routes(filters)[:6],
            deals=offer_rows(db())[:4], latest=latest, popular=popular,
            coding=route_rows(db(), {"tools": "1", "use_case": "coding", "sort": "value", "limit": 3}),
            home_harnesses=rows("SELECT id,name,interfaces,supports_mcp FROM harnesses WHERE name IN ('Hermes Agent','Codex CLI','OpenCode','Pi') ORDER BY name"),
            media_routes=route_rows(db(), {"type": "3D generation", "limit": 3}), changes=changes[:3],
            meta_description="Find current AI model routes, deals, new releases, coding models, harness compatibility, and 3D generation APIs from source-backed data.",
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
        found = compatible_routes(query_filters)
        page_params = {key: value for key, value in filters.items() if key != "page"}
        return render_template(
            "models.html", title="Models & provider routes", filters=display_filters,
            interpreted=interpreted, options=filter_options(db()), routes=found[:page_size],
            page=page, has_more=len(found) > page_size, default_view=not filters,
            prev_url=("/models?" + urlencode({**page_params, "page": page - 1})) if page > 1 else None,
            next_url=("/models?" + urlencode({**page_params, "page": page + 1})) if len(found) > page_size else None,
        )

    @app.get("/models/<int:model_id>")
    def model_detail(model_id):
        model = db().execute("SELECT m.*,l.name lab_name FROM models m LEFT JOIN labs l ON l.id=m.lab_id WHERE m.id=?", (model_id,)).fetchone()
        if not model:
            abort(404)
        return redirect(url_for("model_detail_slug", model_slug=model["canonical_slug"]), code=301)

    @app.get("/models/<path:model_slug>")
    def model_detail_slug(model_slug):
        model = db().execute("SELECT m.*,l.name lab_name FROM models m LEFT JOIN labs l ON l.id=m.lab_id WHERE m.canonical_slug=?", (model_slug,)).fetchone()
        if not model:
            abort(404)
        model_id = model["id"]
        all_offerings = route_rows(db(), {"model_id": model_id, "limit": 250})
        offerings = all_offerings[:12]
        use_cases = rows("SELECT u.name,mus.classification,mus.rationale,mus.confidence FROM model_use_case_scores mus JOIN use_cases u ON u.id=mus.use_case_id WHERE mus.model_id=? ORDER BY u.name", (model_id,))
        benchmarks = rows("SELECT b.name,b.version,br.score,br.metric,br.confidence FROM benchmark_results br JOIN benchmarks b ON b.id=br.benchmark_id WHERE br.model_id=? ORDER BY b.name", (model_id,))
        harnesses = []
        for harness in rows("SELECT id,name FROM harnesses ORDER BY name"):
            supported = [compatibility_for(db(), harness["id"], o["offering_id"]) for o in all_offerings]
            supported = [x for x in supported if x["status"] in {"COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION", "PARTIAL"}]
            if supported:
                harnesses.append({"name": harness["name"], **supported[0]})
        media = db().execute("SELECT * FROM model_media_features WHERE model_id=?", (model_id,)).fetchone()
        verified = max([o["fetched_at"] for o in all_offerings if o["fetched_at"]] + ([media["last_verified_at"]] if media and media["last_verified_at"] else []), default=None)
        return render_template("model_detail.html", title=f"{model['canonical_name']} prices, providers & compatibility", item=dict(model), offerings=offerings, offering_count=len(all_offerings), use_cases=use_cases, benchmarks=benchmarks, harnesses=harnesses, media=dict(media) if media else None, sources=source_rows(db(), model_id=model_id), last_verified_at=verified, canonical_url=request.url_root.rstrip('/') + url_for('model_detail_slug', model_slug=model_slug), meta_description=f"{model['canonical_name']} provider routes, current pricing, limits, tool support, benchmarks, harness compatibility, sources, and verification dates.")

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
        return render_template("route_detail.html", title=f"{route['canonical_name']} via {route['provider_name']}", route=route, history=price_history(db(), offering_id), peers=peers, offers=offers, route_variants=openrouter_variant_rows(db(), offering_id), sources=source_rows(db(), offering_id=offering_id), canonical_url=request.url_root.rstrip('/') + request.path, meta_description=f"Current {route['canonical_name']} pricing, limits, tool support, offers, price history, and sources for the {route['provider_name']} route.")

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
        routes = route_rows(db(), {"provider_id": provider_id, "limit": 250})
        sources = rows("""SELECT DISTINCT s.name,s.url,s.reliability,s.fetched_at FROM sources s WHERE s.id IN (
          SELECT source_id FROM provider_offerings WHERE provider_id=? UNION SELECT source_id FROM plans WHERE provider_id=?
          UNION SELECT source_id FROM offers WHERE provider_id=?) ORDER BY s.reliability,s.name""", (provider_id, provider_id, provider_id))
        verified = max([r["fetched_at"] for r in routes if r["fetched_at"]] + [s["fetched_at"] for s in sources if s["fetched_at"]], default=None)
        return render_template("provider_detail.html", title=f"{provider['name']} AI models, pricing & routes", provider=provider, routes=routes, plans=rows("SELECT * FROM plans WHERE provider_id=?", (provider_id,)), offers=rows("SELECT * FROM offers WHERE provider_id=? ORDER BY status,ends_at", (provider_id,)), sources=sources, last_verified_at=verified, canonical_url=request.url_root.rstrip('/') + url_for('provider_detail_slug', provider_slug=provider_slug), meta_description=f"Documented {provider['name']} AI model routes, current prices, limits, offers, sources, and last verification dates.")

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
        harness = next((h for h in rows("SELECT * FROM harnesses") if slugify(h["name"]) == harness_slug), None)
        if not harness:
            abort(404)
        harness_id = harness["id"]
        capabilities = rows("SELECT transport,state,note FROM harness_mcp_capabilities WHERE harness_id=?", (harness_id,))
        claims = rows("""SELECT hc.*,s.name source_name,s.url source_url FROM harness_claims hc
          JOIN sources s ON s.id=hc.source_id WHERE hc.harness_id=? ORDER BY hc.claim_key""", (harness_id,))
        access_methods = rows("""SELECT ha.*,s.name source_name,s.url source_url FROM harness_access_methods ha
          JOIN sources s ON s.id=ha.source_id WHERE ha.harness_id=? ORDER BY ha.access_method""", (harness_id,))
        routes = []
        for route in route_rows(db()):
            match = compatibility_for(db(), harness_id, route["offering_id"])
            if match["status"] in {"COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION", "PARTIAL"}:
                routes.append({**route, "compatibility": match})
        sources = rows("""SELECT DISTINCT s.name,s.url,s.reliability,s.fetched_at FROM sources s WHERE s.id IN (
          SELECT source_id FROM harnesses WHERE id=? UNION SELECT source_id FROM harness_mcp_capabilities WHERE harness_id=?
          UNION SELECT source_id FROM harness_provider_compatibility WHERE harness_id=?) ORDER BY s.name""", (harness_id, harness_id, harness_id))
        verified = max([s["fetched_at"] for s in sources if s["fetched_at"]], default=None)
        evidence_routes = [route for route in routes if route["compatibility"].get("source")]
        return render_template("harness_detail.html", title=f"{harness['name']} providers, models & MCP compatibility", item=dict(harness), capabilities=capabilities, claims=claims, access_methods=access_methods, routes=evidence_routes or routes[:24], sources=sources, last_verified_at=verified, canonical_url=request.url_root.rstrip('/') + url_for('harness_detail_slug', harness_slug=harness_slug), meta_description=f"Documented {harness['name']} provider integrations, model-route compatibility, MCP capabilities, sources, and caveats.")

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
          m.canonical_name,m.canonical_slug,p.name provider_name,o.context_limit,o.free_status,o.tool_support,
          (SELECT amount FROM pricing_records pr WHERE pr.offering_id=o.id AND pr.price_type='INPUT' AND pr.valid_until IS NULL ORDER BY pr.valid_from DESC LIMIT 1) input_price,
          (SELECT amount FROM pricing_records pr WHERE pr.offering_id=o.id AND pr.price_type='OUTPUT' AND pr.valid_until IS NULL ORDER BY pr.valid_from DESC LIMIT 1) output_price,
          s.url source_url FROM route_compatibility_evidence rce JOIN harnesses h ON h.id=rce.harness_id
          JOIN provider_offerings o ON o.id=rce.offering_id JOIN models m ON m.id=o.model_id
          JOIN providers p ON p.id=o.provider_id JOIN sources s ON s.id=rce.source_id
          WHERE h.id IN (SELECT whc.harness_id FROM workflow_harness_compatibility whc
            JOIN workflow_integrations wi ON wi.id=whc.integration_id WHERE wi.workflow_id=?)
          ORDER BY o.free_status='FREE' DESC,COALESCE(input_price,999999),m.canonical_name""", (workflow["id"],))
        benchmarks = rows("""SELECT b.name,b.version,b.category,br.score,br.metric,m.canonical_name,
          s.url source_url FROM benchmark_results br JOIN benchmarks b ON b.id=br.benchmark_id
          JOIN models m ON m.id=br.model_id LEFT JOIN sources s ON s.id=br.source_id
          WHERE b.category IN ('coding','agentic coding','software engineering')
          ORDER BY b.is_current DESC,br.score DESC LIMIT 20""")
        return render_template("workflow_detail.html", title=f"{workflow['name']} compatibility", workflow=workflow,
          integrations=integrations, hosts=hosts, route_matches=route_matches, benchmarks=benchmarks,
          canonical_url=request.url_root.rstrip('/') + request.path,
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
        return render_template("compare.html", title="Compare routes", routes=selected,
                               all_routes=all_routes, histories=histories, compare_query=compare_query)

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
            canonical_url=request.url_root.rstrip('/') + request.path,
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
        batch = request.args.get("batch") == "1"
        selected_plan = None
        if request.args.get("plan_id", "").isdigit():
            selected_plan = db().execute("""SELECT pl.*,p.name provider_name,s.url source_url
              FROM plans pl JOIN providers p ON p.id=pl.provider_id LEFT JOIN sources s ON s.id=pl.source_id
              WHERE pl.id=?""", (int(request.args["plan_id"]),)).fetchone()
        calculated = []
        for route in compatible_routes(filters):
            if route["input_price"] is None or route["output_price"] is None:
                continue
            cache_price = route["cache_read_price"] if route["cache_read_price"] is not None else route["input_price"]
            total = (input_tokens * ((1-cache_share)*route["input_price"] + cache_share*cache_price) + output_tokens * route["output_price"]) / 1_000_000
            calculated.append({**route, "monthly_cost": total * (.5 if batch and route["batch"] else 1), "batch_applied": batch and route["batch"]})
        calculated = sorted(calculated, key=lambda r: r["monthly_cost"])
        return render_template("calculator.html", title="Cost calculator", filters=filters, options=filter_options(db()), routes=calculated[:12], route_count=len(calculated), plans=plan_rows(db(), {"subscription": "1", "coding": "1"}), selected_plan=dict(selected_plan) if selected_plan else None, input_tokens=input_tokens, output_tokens=output_tokens, cache_share=round(cache_share*100), batch=batch)

    @app.get("/offers")
    def offers():
        differences = pricing_differences(db())
        current_offers = offer_rows(db())
        free_routes = openrouter_free_rows(db())
        return render_template("offers.html", title="Offers & deals", offers=current_offers[:8],
          offer_count=len(current_offers), expired=offer_rows(db(), include_expired=True),
          free_routes=free_routes[:8], free_count=len(free_routes),
          discounts=differences["discounts"][:8], direct_differences=differences["direct"][:8])

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
            base_filters = {"tools": "1", "sort": "value", "limit": 500}
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

    @app.get("/new-releases")
    def releases():
        return render_template("models.html", title="New releases", filters={"release": "week"}, options=filter_options(db()), routes=route_rows(db(), {"release": "week"}))

    @app.get("/benchmarks")
    def benchmarks():
        return render_template("benchmarks.html", title="Benchmarks", benchmarks=rows("SELECT b.*,COUNT(br.id) result_count FROM benchmarks b LEFT JOIN benchmark_results br ON br.benchmark_id=b.id GROUP BY b.id ORDER BY b.is_current DESC,b.name,b.version DESC"), results=rows("SELECT b.name benchmark,b.version,m.canonical_name,br.score,br.metric,br.confidence,br.harness_name,br.scaffold,br.reasoning_setting FROM benchmark_results br JOIN benchmarks b ON b.id=br.benchmark_id JOIN models m ON m.id=br.model_id WHERE b.is_current=1 AND br.confidence IN ('HIGH','MEDIUM') ORDER BY b.name,br.score DESC"))

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
          WHERE br.benchmark_id=? ORDER BY br.score DESC""", (benchmark["id"],))
        source = db().execute("SELECT * FROM sources WHERE id=?", (benchmark["source_id"],)).fetchone() if benchmark["source_id"] else None
        return render_template("benchmark_detail.html", title=f"{benchmark['name']} {benchmark['version']} benchmark", benchmark=benchmark, results=results, source=source, canonical_url=request.url_root.rstrip('/') + request.path, meta_description=f"{benchmark['name']} {benchmark['version']} methodology, metric-specific results, harness details, sources, and caveats.")

    @app.get("/internal/data-quality")
    def internal_data_quality():
        from .data_quality import data_quality_metrics, review_triage, source_health_rows
        return render_template(
            "data_quality.html",
            title="Internal data quality",
            metrics=data_quality_metrics(db()),
            triage=review_triage(db()),
            source_health=source_health_rows(db()),
            robots_meta="noindex,nofollow",
        )

    @app.get("/use-cases/<use_case_slug>")
    def use_case_detail(use_case_slug):
        use_case = db().execute("SELECT * FROM use_cases WHERE slug=?", (use_case_slug,)).fetchone()
        if not use_case:
            abort(404)
        scores = rows("""SELECT m.canonical_name,m.canonical_slug,mus.classification,mus.confidence,mus.rationale,
          s.name source_name,s.url source_url,s.fetched_at FROM model_use_case_scores mus JOIN models m ON m.id=mus.model_id
          LEFT JOIN sources s ON s.id=mus.source_id WHERE mus.use_case_id=?
          ORDER BY CASE mus.classification WHEN 'RECOMMENDED' THEN 0 WHEN 'SUPPORTED' THEN 1 ELSE 2 END,m.canonical_name""", (use_case["id"],))
        return render_template("use_case_detail.html", title=f"AI models for {use_case['name']}", use_case=use_case, scores=scores, canonical_url=request.url_root.rstrip('/') + request.path, meta_description=f"Source-backed AI model routes for {use_case['name']}, with classifications, rationale, confidence, provider links, and verification dates.")

    return app

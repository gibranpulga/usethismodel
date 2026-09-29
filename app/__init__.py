import os
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request

from .db import init_db
from .domain import compatibility_for
from .query import filter_options, route_rows, source_rows

NAV = [("Home", "/"), ("Models", "/models"), ("Providers", "/providers"), ("Harnesses", "/harnesses"), ("Compatibility", "/compatibility"), ("Offers", "/offers"), ("New Releases", "/new-releases"), ("Benchmarks", "/benchmarks"), ("Use Cases", "/use-cases"), ("Compare", "/compare"), ("Calculator", "/calculator")]
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
    if app.config.get("APPLY_DATA_SNAPSHOT", not app.config.get("TESTING", False)):
        from .data_snapshot import apply_snapshot
        from .db import get_db
        with app.app_context():
            apply_snapshot(get_db(), Path(__file__).resolve().parent.parent / "data" / "catalog.json")

    @app.context_processor
    def navigation():
        return {"nav": NAV, "current_path": request.path, "presets": PRESETS}

    def db():
        from .db import get_db
        return get_db()

    def rows(query, params=()):
        return db().execute(query, params).fetchall()

    def finder_filters():
        return {key: value for key, value in request.args.items() if value not in ("", "any", None)}

    def compatible_routes(filters):
        result = route_rows(db(), filters)
        harness_name = filters.get("harness")
        if not harness_name:
            return result
        harness = db().execute("SELECT id FROM harnesses WHERE name=?", (harness_name,)).fetchone()
        if not harness:
            return []
        kept = []
        for route in result:
            match = compatibility_for(db(), harness["id"], route["offering_id"], filters.get("mcp") == "1")
            route["compatibility"] = match
            if match["status"] in {"COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION", "PARTIAL"}:
                kept.append(route)
        return kept

    @app.get("/health")
    def health():
        db().execute("SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1").fetchone()
        return jsonify(status="ok", database="sqlite")

    @app.get("/")
    def home():
        filters = finder_filters()
        return render_template("index.html", filters=filters, options=filter_options(db()), routes=compatible_routes(filters)[:6])

    @app.get("/models")
    def models():
        filters = finder_filters()
        return render_template("models.html", title="Models & provider routes", filters=filters, options=filter_options(db()), routes=compatible_routes(filters))

    @app.get("/models/<int:model_id>")
    def model_detail(model_id):
        model = db().execute("SELECT m.*,l.name lab_name FROM models m LEFT JOIN labs l ON l.id=m.lab_id WHERE m.id=?", (model_id,)).fetchone()
        if not model:
            abort(404)
        offerings = [o for o in route_rows(db(), {"q": model["canonical_name"]}) if o["model_id"] == model_id]
        use_cases = rows("SELECT u.name,mus.classification,mus.rationale,mus.confidence FROM model_use_case_scores mus JOIN use_cases u ON u.id=mus.use_case_id WHERE mus.model_id=? ORDER BY u.name", (model_id,))
        benchmarks = rows("SELECT b.name,b.version,br.score,br.metric,br.confidence FROM benchmark_results br JOIN benchmarks b ON b.id=br.benchmark_id WHERE br.model_id=? ORDER BY b.name", (model_id,))
        harnesses = []
        for harness in rows("SELECT id,name FROM harnesses ORDER BY name"):
            supported = [compatibility_for(db(), harness["id"], o["offering_id"]) for o in offerings]
            supported = [x for x in supported if x["status"] in {"COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION", "PARTIAL"}]
            if supported:
                harnesses.append({"name": harness["name"], **supported[0]})
        return render_template("model_detail.html", title=model["canonical_name"], item=dict(model), offerings=offerings, use_cases=use_cases, benchmarks=benchmarks, harnesses=harnesses, sources=source_rows(db(), model_id=model_id))

    @app.get("/providers")
    def providers():
        providers = rows("SELECT p.id,p.name,p.website_url,COUNT(o.id) route_count FROM providers p LEFT JOIN provider_offerings o ON o.provider_id=p.id GROUP BY p.id ORDER BY p.name")
        return render_template("providers.html", title="Providers", providers=providers)

    @app.get("/providers/<int:provider_id>")
    def provider_detail(provider_id):
        provider = db().execute("SELECT * FROM providers WHERE id=?", (provider_id,)).fetchone()
        if not provider:
            abort(404)
        routes = [r for r in route_rows(db()) if r["provider_id"] == provider_id]
        return render_template("provider_detail.html", title=provider["name"], provider=provider, routes=routes, plans=rows("SELECT * FROM plans WHERE provider_id=?", (provider_id,)), offers=rows("SELECT * FROM offers WHERE provider_id=? ORDER BY status,ends_at", (provider_id,)), sources=source_rows(db(), offering_id=routes[0]["offering_id"]) if routes else [])

    @app.get("/harnesses")
    def harnesses():
        return render_template("harnesses.html", title="Harnesses", harnesses=rows("SELECT * FROM harnesses ORDER BY name"))

    @app.get("/harnesses/<int:harness_id>")
    def harness_detail(harness_id):
        harness = db().execute("SELECT * FROM harnesses WHERE id=?", (harness_id,)).fetchone()
        if not harness:
            abort(404)
        capabilities = rows("SELECT transport,state,note FROM harness_mcp_capabilities WHERE harness_id=?", (harness_id,))
        routes = []
        for route in route_rows(db()):
            match = compatibility_for(db(), harness_id, route["offering_id"])
            if match["status"] in {"COMPATIBLE", "COMPATIBLE_WITH_CONFIGURATION", "PARTIAL"}:
                routes.append({**route, "compatibility": match})
        return render_template("harness_detail.html", title=harness["name"], item=dict(harness), capabilities=capabilities, routes=routes)

    @app.get("/compatibility")
    def compatibility():
        filters = finder_filters()
        return render_template("compatibility.html", title="Compatibility finder", filters=filters, options=filter_options(db()), routes=compatible_routes(filters) if filters.get("harness") else [])

    @app.get("/compare")
    def compare():
        ids = [int(value) for value in request.args.get("ids", "").split(",") if value.isdigit()][:5]
        all_routes = route_rows(db())
        return render_template("compare.html", title="Compare routes", routes=[r for r in all_routes if r["offering_id"] in ids], all_routes=all_routes)

    @app.get("/calculator")
    def calculator():
        filters = finder_filters()
        input_tokens = int(request.args.get("input_tokens", 1_000_000) or 0)
        output_tokens = int(request.args.get("output_tokens", 250_000) or 0)
        cache_share = min(100, max(0, int(request.args.get("cache_share", 0) or 0))) / 100
        batch = request.args.get("batch") == "1"
        calculated = []
        for route in compatible_routes(filters):
            if route["input_price"] is None or route["output_price"] is None:
                continue
            cache_price = route["cache_read_price"] if route["cache_read_price"] is not None else route["input_price"]
            total = (input_tokens * ((1-cache_share)*route["input_price"] + cache_share*cache_price) + output_tokens * route["output_price"]) / 1_000_000
            calculated.append({**route, "monthly_cost": total * (.5 if batch and route["batch"] else 1), "batch_applied": batch and route["batch"]})
        return render_template("calculator.html", title="Cost calculator", filters=filters, options=filter_options(db()), routes=sorted(calculated, key=lambda r: r["monthly_cost"]), input_tokens=input_tokens, output_tokens=output_tokens, cache_share=round(cache_share*100), batch=batch)

    @app.get("/offers")
    def offers():
        return render_template("offers.html", title="Offers", offers=rows("SELECT x.*,p.name provider_name FROM offers x JOIN providers p ON p.id=x.provider_id WHERE x.status='ACTIVE' AND (x.ends_at IS NULL OR x.ends_at>=date('now')) ORDER BY p.name"))

    @app.get("/new-releases")
    def releases():
        return render_template("models.html", title="New releases", filters={"release": "week"}, options=filter_options(db()), routes=route_rows(db(), {"release": "week"}))

    @app.get("/benchmarks")
    def benchmarks():
        return render_template("benchmarks.html", title="Benchmarks", benchmarks=rows("SELECT b.*,COUNT(br.id) result_count FROM benchmarks b LEFT JOIN benchmark_results br ON br.benchmark_id=b.id GROUP BY b.id ORDER BY b.name"), results=rows("SELECT b.name benchmark,m.canonical_name,br.score,br.metric,br.confidence FROM benchmark_results br JOIN benchmarks b ON b.id=br.benchmark_id JOIN models m ON m.id=br.model_id ORDER BY b.name,br.score DESC"))

    @app.get("/use-cases")
    def use_cases():
        return render_template("use_cases.html", title="Use cases", use_cases=filter_options(db())["use_cases"])

    return app

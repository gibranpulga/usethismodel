import os
from pathlib import Path

from flask import Flask, abort, jsonify, render_template

from .db import init_db


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.getenv("FLASK_SECRET_KEY", "local-development-key"),
        DATABASE=os.getenv("DATABASE_PATH", str(Path(app.instance_path) / "usethismodel.sqlite3")),
    )
    if test_config:
        app.config.update(test_config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    init_db(app)

    @app.get("/health")
    def health():
        from .db import get_db

        get_db().execute("SELECT 1").fetchone()
        return jsonify(status="ok", database="sqlite")

    @app.get("/")
    def home():
        sections = [
            "Models",
            "Providers",
            "Harnesses",
            "Compatibility",
            "Offers",
            "New Releases",
            "Benchmarks",
            "Use Cases",
            "Compare",
            "Calculator",
        ]
        return render_template("index.html", sections=sections)

    def rows(query, params=()):
        from .db import get_db

        return get_db().execute(query, params).fetchall()

    @app.get("/models")
    def models():
        return render_template(
            "catalog.html",
            title="Models",
            columns=["Model", "Lab", "Offerings", "Status"],
            rows=rows(
                """SELECT m.id, m.canonical_name label, COALESCE(l.name,m.vendor) detail, COUNT(o.id) count, m.status FROM models m LEFT JOIN labs l ON l.id=m.lab_id LEFT JOIN provider_offerings o ON o.model_id=m.id GROUP BY m.id ORDER BY m.canonical_name"""
            ),
            detail_prefix="/models",
        )

    @app.get("/models/<int:model_id>")
    def model_detail(model_id):
        model = rows(
            "SELECT m.*, l.name lab_name FROM models m LEFT JOIN labs l ON l.id=m.lab_id WHERE m.id=?",
            (model_id,),
        )
        if not model:
            abort(404)
        offerings = rows(
            """SELECT o.*,p.name provider_name FROM provider_offerings o JOIN providers p ON p.id=o.provider_id WHERE o.model_id=? ORDER BY p.name""",
            (model_id,),
        )
        return render_template(
            "detail.html",
            title=model[0]["canonical_name"],
            item=dict(model[0]),
            offerings=offerings,
            kind="Model",
        )

    @app.get("/providers")
    def providers():
        return render_template(
            "catalog.html",
            title="Providers",
            columns=["Provider", "Offerings", "Website"],
            rows=rows(
                """SELECT p.id,p.name label,p.website_url detail,COUNT(o.id) count,'' status FROM providers p LEFT JOIN provider_offerings o ON o.provider_id=p.id GROUP BY p.id ORDER BY p.name"""
            ),
            detail_prefix="/providers",
        )

    @app.get("/providers/<int:provider_id>")
    def provider_detail(provider_id):
        provider = rows("SELECT * FROM providers WHERE id=?", (provider_id,))
        if not provider:
            abort(404)
        offerings = rows(
            """SELECT o.*,m.canonical_name model_name FROM provider_offerings o JOIN models m ON m.id=o.model_id WHERE o.provider_id=? ORDER BY m.canonical_name""",
            (provider_id,),
        )
        return render_template(
            "detail.html",
            title=provider[0]["name"],
            item=dict(provider[0]),
            offerings=offerings,
            kind="Provider",
        )

    @app.get("/harnesses")
    def harnesses():
        return render_template(
            "catalog.html",
            title="Harnesses",
            columns=["Harness", "Organization", "Interfaces", "MCP"],
            rows=rows(
                "SELECT id,name label,organization detail,interfaces count,COALESCE(supports_mcp,'UNKNOWN') status FROM harnesses ORDER BY name"
            ),
            detail_prefix="/harnesses",
        )

    @app.get("/harnesses/<int:harness_id>")
    def harness_detail(harness_id):
        harness = rows("SELECT * FROM harnesses WHERE id=?", (harness_id,))
        if not harness:
            abort(404)
        capabilities = rows(
            "SELECT transport,state,note FROM harness_mcp_capabilities WHERE harness_id=?",
            (harness_id,),
        )
        return render_template(
            "harness_detail.html",
            title=harness[0]["name"],
            item=dict(harness[0]),
            capabilities=capabilities,
        )

    @app.get("/benchmarks")
    def benchmarks():
        return render_template(
            "catalog.html",
            title="Benchmarks",
            columns=["Benchmark", "Version", "Category"],
            rows=rows(
                "SELECT id,name label,version detail,category count,'' status FROM benchmarks ORDER BY name"
            ),
            detail_prefix="/benchmarks",
        )

    @app.get("/<section>")
    def placeholder(section):
        labels = {
            "models": "Models",
            "providers": "Providers",
            "harnesses": "Harnesses",
            "compatibility": "Compatibility",
            "offers": "Offers",
            "new-releases": "New Releases",
            "benchmarks": "Benchmarks",
            "use-cases": "Use Cases",
            "compare": "Compare",
            "calculator": "Calculator",
        }
        label = labels.get(section)
        if not label:
            return render_template(
                "index.html",
                sections=[
                    "Models",
                    "Providers",
                    "Harnesses",
                    "Compatibility",
                    "Offers",
                    "New Releases",
                    "Benchmarks",
                    "Use Cases",
                    "Compare",
                    "Calculator",
                ],
            ), 404
        return render_template("placeholder.html", label=label)

    return app

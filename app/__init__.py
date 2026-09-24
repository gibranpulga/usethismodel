import os
from pathlib import Path

from flask import Flask, jsonify, render_template

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
        sections = ["Models", "Providers", "Harnesses", "Compatibility", "Offers", "New Releases", "Benchmarks", "Use Cases", "Compare", "Calculator"]
        return render_template("index.html", sections=sections)

    @app.get("/<section>")
    def placeholder(section):
        labels = {"models": "Models", "providers": "Providers", "harnesses": "Harnesses", "compatibility": "Compatibility", "offers": "Offers", "new-releases": "New Releases", "benchmarks": "Benchmarks", "use-cases": "Use Cases", "compare": "Compare", "calculator": "Calculator"}
        label = labels.get(section)
        if not label:
            return render_template("index.html", sections=["Models", "Providers", "Harnesses", "Compatibility", "Offers", "New Releases", "Benchmarks", "Use Cases", "Compare", "Calculator"]), 404
        return render_template("placeholder.html", label=label)

    return app

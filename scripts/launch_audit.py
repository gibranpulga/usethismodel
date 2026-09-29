"""Local public-launch audit for canonical pages, metadata, schemas, and links."""

from __future__ import annotations

import json
import re
import sys
import tempfile
from html import unescape
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402

TARGETS = [
    "/", "/models/glm-5-3", "/models/deepseek-v4-pro", "/providers/openrouter",
    "/providers/z-ai", "/harnesses/opencode", "/harnesses/hermes", "/harnesses/pi",
    "/harnesses/codex", "/use-cases/free-tool-calling", "/use-cases/agentic-coding",
    "/use-cases/long-context", "/use-cases/3d-generation", "/workflows/unreal-engine",
    "/workflows/reaper", "/deals", "/releases",
]
HREF = re.compile(r'href=["\']([^"\']+)', re.I)
SCHEMA = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.I | re.S)


def main():
    with tempfile.TemporaryDirectory() as temporary:
        app = create_app({"TESTING": True, "APPLY_DATA_SNAPSHOT": True,
                          "DATABASE": temporary + "/audit.sqlite3"})
        client = app.test_client()
        return audit(client)


def audit(client):
    failures = []
    links = set()
    for path in TARGETS:
        response = client.get(path, headers={"User-Agent": "UseThisModel launch audit/1.0"})
        body = response.get_data(as_text=True)
        if response.status_code != 200:
            failures.append(f"{path}: HTTP {response.status_code}")
            continue
        for marker in ('<title>', 'name="description"', 'rel="canonical"', 'name="robots" content="index,follow"'):
            if marker not in body:
                failures.append(f"{path}: missing {marker}")
        for raw in SCHEMA.findall(body):
            try:
                json.loads(unescape(raw))
            except json.JSONDecodeError as exc:
                failures.append(f"{path}: invalid JSON-LD ({exc.msg})")
        for href in HREF.findall(body):
            parsed = urlsplit(unescape(href))
            if not parsed.scheme and parsed.path.startswith("/") and not parsed.path.startswith("/static/"):
                links.add(parsed.path)
    for path in sorted(links):
        if client.get(path, headers={"User-Agent": "UseThisModel launch audit/1.0"}).status_code >= 400:
            failures.append(f"broken internal link: {path}")
    for path, marker in [("/robots.txt", "OAI-SearchBot"), ("/sitemap.xml", "sitemapindex"),
                         ("/feeds/changes.json", "jsonfeed.org")]:
        response = client.get(path)
        if response.status_code != 200 or marker not in response.get_data(as_text=True):
            failures.append(f"{path}: missing or invalid")
    print(json.dumps({"status": "failed" if failures else "ok", "pages": len(TARGETS),
                      "internal_links": len(links), "failures": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

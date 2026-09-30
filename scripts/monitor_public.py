"""Dependency-free public monitor with actionable JSON output and exit status."""

from __future__ import annotations

import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://usethismodel.codefiction.net"
CHECKS = {
    "homepage": "/",
    "crawler_homepage": "/",
    "health": "/health",
    "data_quality": "/health/readiness",
    "robots": "/robots.txt",
    "sitemap": "/sitemap.xml",
    "llms": "/llms.txt",
    "api_docs": "/api",
    "openapi": "/api/v1/openapi.json",
    "key_model": "/models/glm-5-3",
    "key_provider": "/providers/openrouter",
    "change_feed": "/feeds/changes.json",
}

REQUIRED = {
    "homepage": (b"UseThisModel", b"What model should I use?", b'href="/models"'),
    "crawler_homepage": (b"UseThisModel", b"What model should I use?"),
    "robots": (b"User-agent: OAI-SearchBot", b"Sitemap: https://"),
    "sitemap": (b"<sitemapindex", b"https://usethismodel.codefiction.net/sitemaps/"),
    "llms": (b"# UseThisModel", b"Public API documentation:"),
    "api_docs": (b"UseThisModel public API v1", b"/api/v1/openapi.json"),
    "openapi": (b'"openapi":"3.1.0"', b'"/api/v1/models"'),
    "key_model": (b"GLM-5.3", b"Last verified"),
}


def main(base=BASE):
    failures = []
    results = {}
    for name, path in CHECKS.items():
        try:
            agent = ("Mozilla/5.0 AppleWebKit/537.36; compatible; OAI-SearchBot/1.4; "
                     "+https://openai.com/searchbot" if name == "crawler_homepage"
                     else "UseThisModel public monitor/1.0")
            request = Request(base.rstrip("/") + path, headers={"User-Agent": agent})
            with urlopen(request, timeout=20) as response:
                body = response.read(128 * 1024)
                results[name] = {"status": response.status, "bytes_sampled": len(body)}
                if response.status != 200 or not body:
                    failures.append(f"{name}: expected a non-empty HTTP 200 at {path}")
                for marker in REQUIRED.get(name, ()):
                    if marker not in body:
                        failures.append(f"{name}: response at {path} lacks {marker!r}")
                if name in {"homepage", "crawler_homepage", "key_model", "key_provider"}:
                    if b'<meta name="robots" content="noindex' in body:
                        failures.append(f"{name}: public page unexpectedly carries noindex")
                    if b'<link rel="canonical" href="http://' in body:
                        failures.append(f"{name}: canonical URL is not HTTPS")
        except HTTPError as exc:
            failures.append(f"{name}: HTTP {exc.code} at {path}; inspect deployment/source health")
        except URLError as exc:
            failures.append(f"{name}: unreachable at {path} ({exc.reason})")
    print(json.dumps({"status": "failed" if failures else "ok", "base": base,
                      "checks": results, "actions": failures}, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else BASE))

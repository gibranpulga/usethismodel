"""Dependency-free public monitor with actionable JSON output and exit status."""

from __future__ import annotations

import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE = "https://usethismodel.com"
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
    "sitemap": (b"<sitemapindex", b"https://usethismodel.com/sitemaps/"),
    "llms": (b"# UseThisModel", b"Public API documentation:"),
    "api_docs": (b"UseThisModel public API v1", b"/api/v1/openapi.json"),
    "openapi": (b'"openapi":"3.1.0"', b'"/api/v1/models"'),
    "key_model": (b"GLM-5.3", b"Last verified"),
}


class NoRedirect(HTTPRedirectHandler):
    def http_error_301(self, req, fp, code, msg, headers):
        return fp

    http_error_302 = http_error_301
    http_error_303 = http_error_301
    http_error_307 = http_error_301
    http_error_308 = http_error_301


def main(base=BASE):
    failures = []
    results = {}
    for name, path in CHECKS.items():
        try:
            agent = ("Mozilla/5.0 AppleWebKit/537.36; compatible; OAI-SearchBot/1.4; "
                     "+https://openai.com/searchbot" if name == "crawler_homepage"
                     else "UseThisModel public monitor/1.0")
            request = Request(base.rstrip("/") + path, headers={"User-Agent": agent})
            with build_opener().open(request, timeout=20) as response:
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

    redirect_opener = build_opener(NoRedirect)
    redirect_checks = {
        "http_to_https": ("http://usethismodel.com/models/glm-5-3?tools=true", (301, 308),
                           "https://usethismodel.com/models/glm-5-3?tools=true"),
        "old_host": ("https://usethismodel.codefiction.net/models/glm-5-3?tools=true", (301, 308),
                     "https://usethismodel.com/models/glm-5-3?tools=true"),
    }
    for name, (url, expected_status, expected_location) in redirect_checks.items():
        try:
            response = redirect_opener.open(Request(url), timeout=20)
            location = response.headers.get("Location")
            if response.status not in expected_status or location != expected_location:
                failures.append(f"{name}: expected {expected_status} to {expected_location}, got {response.status} to {location}")
            results[name] = {"status": response.status, "location": location}
        except HTTPError as exc:
            location = exc.headers.get("Location")
            if exc.code not in expected_status or location != expected_location:
                failures.append(f"{name}: expected {expected_status} to {expected_location}, got {exc.code} to {location}")
            results[name] = {"status": exc.code, "location": location}
        except URLError as exc:
            failures.append(f"{name}: unreachable ({exc.reason})")
    print(json.dumps({"status": "failed" if failures else "ok", "base": base,
                      "checks": results, "actions": failures}, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else BASE))

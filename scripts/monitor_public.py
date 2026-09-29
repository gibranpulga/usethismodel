"""Dependency-free public monitor with actionable JSON output and exit status."""

from __future__ import annotations

import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://usethismodel.codefiction.net"
CHECKS = {
    "site": "/health",
    "data_quality": "/health/readiness",
    "robots": "/robots.txt",
    "sitemap": "/sitemap.xml",
    "key_model": "/models/glm-5-3",
    "key_provider": "/providers/openrouter",
    "change_feed": "/feeds/changes.json",
}


def main(base=BASE):
    failures = []
    results = {}
    for name, path in CHECKS.items():
        try:
            request = Request(base.rstrip("/") + path, headers={"User-Agent": "UseThisModel public monitor/1.0"})
            with urlopen(request, timeout=20) as response:
                body = response.read(4096)
                results[name] = {"status": response.status, "bytes_sampled": len(body)}
                if response.status != 200 or not body:
                    failures.append(f"{name}: expected a non-empty HTTP 200 at {path}")
        except HTTPError as exc:
            failures.append(f"{name}: HTTP {exc.code} at {path}; inspect deployment/source health")
        except URLError as exc:
            failures.append(f"{name}: unreachable at {path} ({exc.reason})")
    print(json.dumps({"status": "failed" if failures else "ok", "base": base,
                      "checks": results, "actions": failures}, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else BASE))

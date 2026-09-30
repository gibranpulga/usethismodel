# Public monitoring

`python scripts/monitor_public.py` checks HTTPS health, data-quality thresholds,
crawler policy, the sitemap, a representative model/provider page, and the
change feed. It prints one bounded JSON record and exits nonzero with an
actionable failing component. Run it from an external scheduler every five
minutes and alert on a nonzero exit; this catches site and deployment failures.

MCP uses a shared SQLite fixed-window request counter so limits apply across
application workers. `/api/v1` has a separate configurable default of 120
requests per minute; MCP defaults to 60. `TRUSTED_PROXY_CIDRS` is a comma
separated list of exact proxy CIDRs. Forwarded client addresses are ignored
unless the immediate peer is inside that list. Configure the edge proxy to
overwrite `X-Forwarded-For` and rate-limit `/mcp` and `/api/v1/` there as well;
the application limiter is a secondary guard, not a substitute for ingress
capacity controls. For nginx, use a shared `limit_req_zone $binary_remote_addr`
in `http` and `limit_req` on those locations. Do not add the whole Internet to
`TRUSTED_PROXY_CIDRS`.

MCP collection resources return at most 1,000 metadata records; use paginated
tools for larger collections. Compatibility searches inspect at most 10,000
candidate routes per call, and tool pages return at most 50 items. API route
pages cap at 250; compatibility API queries inspect at most 10,000 candidates.
Rate-limit hits emit a prompt-free `mcp_rate_limit_hit` security log event.
Public JSON GET endpoints use a 60-second shared-cache window. Slow MCP/API
requests emit the normalized endpoint class, method, status, and duration; URLs,
query strings, request bodies, and search prompts are not recorded.
Repeated MCP compatibility results are cached in process for 30 seconds, keyed
by the applied snapshot digest and filters; `MCP_COMPATIBILITY_CACHE_SECONDS`
can tune the short TTL, and the four-entry bound limits memory use.

`/health/readiness` also catches source failures and large catalog regressions.
`/health` reports the applied catalog snapshot digest; the daily updater checks it
against the published digest after deployment.
Production baselines default to 100 active models and 100 active routes and can
be tightened with `HEALTH_MIN_MODELS` and `HEALTH_MIN_ROUTES`. The existing
daily updater exits nonzero for source, validation, test, Git, cron, or deploy
trigger failures and writes private status reports under `state/reports/`.
Alert the cron supervisor when that command fails or no report is produced for
36 hours. Keep those private operational reports out of public web routes.

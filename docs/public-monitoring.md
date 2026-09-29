# Public monitoring

`python scripts/monitor_public.py` checks HTTPS health, data-quality thresholds,
crawler policy, the sitemap, a representative model/provider page, and the
change feed. It prints one bounded JSON record and exits nonzero with an
actionable failing component. Run it from an external scheduler every five
minutes and alert on a nonzero exit; this catches site and deployment failures.

`/health/readiness` also catches source failures and large catalog regressions.
Production baselines default to 100 active models and 100 active routes and can
be tightened with `HEALTH_MIN_MODELS` and `HEALTH_MIN_ROUTES`. The existing
daily updater exits nonzero for source, validation, test, Git, cron, or deploy
trigger failures and writes private status reports under `state/reports/`.
Alert the cron supervisor when that command fails or no report is produced for
36 hours. Keep those private operational reports out of public web routes.

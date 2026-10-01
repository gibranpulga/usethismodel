# Brand logo system

Frontend lab and provider marks resolve through `app/logo_system.py` and render through the shared `logo()` template helper. Assets are local under `app/static/logos/labs/` and `app/static/logos/providers/`; no remote logo requests occur at runtime. Source and license notes are recorded in [logo-sources.md](logo-sources.md).

Unknown brands use a small accessible initials fallback. The fallback is hidden from assistive technology when adjacent visible text already names the entity.

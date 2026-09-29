.PHONY: data-update data-dry-run data-validate test launch-audit monitor
PYTHON ?= .venv/bin/python
DATABASE ?= instance/usethismodel.sqlite3

data-update:
	$(PYTHON) -m app.data_update update --database $(DATABASE) --base-snapshot data/catalog.json

data-dry-run:
	$(PYTHON) -m app.data_update update --database $(DATABASE) --base-snapshot data/catalog.json --dry-run

data-validate:
	$(PYTHON) -m app.data_update validate --database $(DATABASE)

test:
	$(PYTHON) -m pytest -q
	$(PYTHON) -m ruff check .

launch-audit:
	$(PYTHON) scripts/launch_audit.py

monitor:
	$(PYTHON) scripts/monitor_public.py

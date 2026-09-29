.PHONY: data-update data-dry-run data-validate test
PYTHON ?= .venv/bin/python
DATABASE ?= instance/usethismodel.sqlite3

data-update:
	$(PYTHON) -m app.data_update update --database $(DATABASE)

data-dry-run:
	$(PYTHON) -m app.data_update update --database $(DATABASE) --dry-run

data-validate:
	$(PYTHON) -m app.data_update validate --database $(DATABASE)

test:
	$(PYTHON) -m pytest -q
	$(PYTHON) -m ruff check .

PYTHON ?= python3

.PHONY: test lint run
test:
	$(PYTHON) -m coverage run -m unittest discover -s tests -v
	$(PYTHON) -m coverage report

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m mypy --python-version 3.11 gps/db.py gps/services.py gps/history.py gps/imports.py gps/inventory.py

run:
	sh ./iniciar.sh

.PHONY: test doctor status release license-check
PYTHON ?= python3

test:
	PYTHONPATH=. $(PYTHON) -m unittest discover -s tests -q

doctor:
	$(PYTHON) rfg.py doctor --format json

status:
	$(PYTHON) rfg.py status --format json

license-check:
	$(PYTHON) scripts/license-check.py

release:
	sh scripts/release.sh

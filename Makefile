PYTHON ?= python3
CASE ?= examples/unitsum
TARE = cd $(CASE) && PYTHONPATH="$(CURDIR)" $(PYTHON) -m tare

.PHONY: answer-key replay offline test

answer-key:
	$(TARE) answer-key

replay:
	$(TARE) reproduce

offline:
	$(TARE) reproduce --offline

test:
	$(PYTHON) -m unittest discover -s tests -t .

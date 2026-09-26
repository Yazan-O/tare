# Thin wrapper: every target calls the Python CLI on one case (default: the self-test fixture).
# Windows: make PYTHON=python
PYTHON ?= python3
CASE ?= examples/unitsum
TARE = cd $(CASE) && PYTHONPATH="$(CURDIR)" $(PYTHON) -m tare

.PHONY: answer-key replay offline test

# run the original COBOL job under GnuCOBOL and record fixtures/answer_key/
answer-key:
	$(TARE) answer-key

# answer key (if cobc), every declared side whose toolchain is present, scoreboard
replay:
	$(TARE) reproduce

# committed fixtures only: seconds, Python only
offline:
	$(TARE) reproduce --offline

test:
	$(PYTHON) -m unittest discover -s tests -t .

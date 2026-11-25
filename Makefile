.PHONY: lint test check

lint:
	python3 tools/check.py --lint

test:
	python3 tools/check.py --test

check:
	python3 tools/check.py

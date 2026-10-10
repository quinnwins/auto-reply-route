.PHONY: all test validate init-dna queue watch install help

# Default target runs the full verification test suite
all: test

# 1. Comprehensive Test Suite (484 tests)
test:
	python3 -m pytest tests/ -v

# 2. Lint and Validate Route Playbooks
validate:
	python3 -m auto_reply_route.cli validate playbooks/ship-feature.route.md

# 3. Bootstrap Operator DNA Matrix
init-dna:
	python3 -m auto_reply_route.cli init-dna

# 4. List Active Queued Messages
queue:
	python3 -m auto_reply_route.cli queue list

# 5. Live Watcher Snapshot
watch:
	python3 -m auto_reply_route.cli watch --once

# 6. Install Package Locally (Editable)
install:
	pip install -e .

help:
	@echo "Auto-Reply Route Development Targets:"
	@echo "  make test             Run full 484-test pytest suite"
	@echo "  make validate         Validate canonical ship-feature playbook"
	@echo "  make init-dna         Bootstrap Operator DNA matrix from AGENTS.md"
	@echo "  make queue            Inspect active Antigravity queued messages"
	@echo "  make watch            Render one-shot queue status card"
	@echo "  make install          Install package in editable mode"

# Shared make targets. Set project variables in the Makefile before
# `include kit.mk`; add project targets after it.
#
#   PYTHON_VERSION   uv python install            (default 3.12)
#   SYNC_ARGS        uv sync arguments            (default --all-groups)
#   TEST_ARGS        pytest arguments for `tests` (default: whole suite)

.DEFAULT_GOAL := help

PYTHON_VERSION ?= 3.12
SYNC_ARGS ?= --all-groups
HOOK_TYPES ?= --hook-type pre-commit --hook-type commit-msg --hook-type pre-push
TEST_ARGS ?=

.PHONY: help install upgrade-check upgrade upgrade-pin clean prek prek-all tests \
	check

help: ## Show available targets
	@printf "Available targets:\n"
	@grep -hE '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

install: ## Set up the development environment
	uv python install $(PYTHON_VERSION)
	uv sync $(SYNC_ARGS)
	@if [ "$$(git rev-parse --git-dir)" = "$$(git rev-parse --git-common-dir)" ]; then \
		uv run prek install $(HOOK_TYPES); \
		echo "prek hooks installed. Re-run after cloning."; \
	else \
		echo "Secondary worktree: git hooks are shared and tied to one venv; run 'make install' in the main checkout."; \
	fi

upgrade-check: ## List outdated packages, action pins and uv
	uv run python scripts/upgrade.py --check

upgrade: ## Upgrade them all except the protected items
	uv run python scripts/upgrade.py --apply

upgrade-pin: ## Move the configured library pin to its branch head (a review PR)
	uv run python scripts/upgrade.py --pin

clean: ## Remove virtual environment and cache files; uninstalls the git hooks in the main checkout
	@if [ "$$(git rev-parse --git-dir)" = "$$(git rev-parse --git-common-dir)" ]; then \
		uv run prek uninstall || true; \
	fi
	rm -rf .venv/
	find . -type d -name "__pycache__" -exec rm -r {} +
	find . -type d \( -name ".cache" -o -name "*__pycache__" -o -name ".*_cache" \) -exec rm -rf {} + 2>/dev/null || true

prek: ## Run git hook checks on changed files
	uv run prek run --fail-fast

prek-all: ## Run git hook checks on all files
	uv run prek run --all-files

tests: ## Run the test suite
	uv run pytest $(TEST_ARGS)

push-check: ## Pre-push: tests + prek-all
	$(MAKE) tests
	$(MAKE) prek-all

check: ## Tests and all quality hooks
	$(MAKE) push-check

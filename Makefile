# Makefile for Chameleon Home Assistant Integration
# Run 'make help' to see available commands.
#
# Note: Lint, format, type checking, YAML lint, markdown format, and
# conventional-commit validation all run automatically via pre-commit hooks
# (configured in .pre-commit-config.yaml). To run them manually against the
# whole tree, use `pre-commit run --all-files`. CI also runs them on PRs.

.DEFAULT_GOAL := help
.PHONY: help setup test clean clean-all deploy \
        dev-setup dev-start dev-stop dev-restart dev-logs dev-shell dev-status

# Colors
BLUE := $(shell printf '\033[0;34m')
GREEN := $(shell printf '\033[0;32m')
NC := $(shell printf '\033[0m')

# Paths
SRC := custom_components/chameleon

#──────────────────────────────────────────────────────────────────────────────
# Setup
#──────────────────────────────────────────────────────────────────────────────

setup: ## Setup development environment (installs tools and pre-commit hooks)
	@./scripts/setup-dev.sh

#──────────────────────────────────────────────────────────────────────────────
# Testing
#──────────────────────────────────────────────────────────────────────────────

test: ## Run all tests with coverage
	@echo "$(BLUE)Running tests...$(NC)"
	@pytest tests/ -v --cov=custom_components.chameleon --cov-report=term-missing

#──────────────────────────────────────────────────────────────────────────────
# Cleaning
#──────────────────────────────────────────────────────────────────────────────

clean: ## Clean build artifacts and caches
	@echo "$(BLUE)Cleaning...$(NC)"
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@echo "$(GREEN)OK$(NC) Cleaned"

clean-all: clean ## Clean everything including venv
	@rm -rf .venv
	@echo "$(GREEN)OK$(NC) Cleaned all (including venv)"

#──────────────────────────────────────────────────────────────────────────────
# Development Server
#──────────────────────────────────────────────────────────────────────────────

dev-setup: ## Setup development environment and start dev server
	@echo "$(BLUE)Setting up Chameleon development environment$(NC)"
	@$(MAKE) --no-print-directory setup
	@./scripts/dev-server.sh start

dev-start: ## Start the Home Assistant dev server
	@./scripts/dev-server.sh start

dev-stop: ## Stop the Home Assistant dev server
	@./scripts/dev-server.sh stop

dev-restart: ## Restart the dev server (reload code changes)
	@./scripts/dev-server.sh restart

dev-logs: ## Show dev server logs (follow mode)
	@./scripts/dev-server.sh logs

dev-shell: ## Open a shell in the dev container
	@./scripts/dev-server.sh shell

dev-status: ## Show dev server status
	@./scripts/dev-server.sh status

#──────────────────────────────────────────────────────────────────────────────
# Deployment
#──────────────────────────────────────────────────────────────────────────────

# Load .env file if it exists
-include .env
export

# Set these in .env or environment:
#   REMOTE_HOST=your-ha-server
#   REMOTE_PATH=/config  (base HA config path, /custom_components/chameleon is auto-appended)

DEPLOY_PATH := $(REMOTE_PATH)/custom_components/chameleon

deploy: ## Deploy to production HA server via rsync
ifndef REMOTE_HOST
	$(error REMOTE_HOST is not set. Add it to .env or export it.)
endif
ifndef REMOTE_PATH
	$(error REMOTE_PATH is not set. Add it to .env or export it.)
endif
	@echo "$(BLUE)Deploying to $(REMOTE_HOST):$(DEPLOY_PATH)...$(NC)"
	@rsync -avz --delete --exclude="__pycache__" $(SRC)/ $(REMOTE_HOST):$(DEPLOY_PATH)/
	@echo "$(GREEN)OK$(NC) Deployed. Restart Home Assistant to apply changes."

#──────────────────────────────────────────────────────────────────────────────
# Help
#──────────────────────────────────────────────────────────────────────────────

help: ## Show this help message
	@echo ""
	@echo "$(BLUE)Chameleon - Home Assistant Integration$(NC)"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' Makefile | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-15s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "Lint, format, and type checks run automatically via pre-commit hooks."
	@echo "Run them manually with: $(GREEN)pre-commit run --all-files$(NC)"
	@echo ""

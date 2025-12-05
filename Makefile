# Makefile for Chameleon Home Assistant Integration
# Run 'make help' to see available commands

.DEFAULT_GOAL := help
.PHONY: help setup lint format check type clean install-hooks deploy

# Colors
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[1;33m
NC := \033[0m

# Paths
SRC := custom_components/chameleon

#──────────────────────────────────────────────────────────────────────────────
# Setup
#──────────────────────────────────────────────────────────────────────────────

setup: ## Setup development environment (installs tools and hooks)
	@./scripts/setup-dev.sh

install-hooks: ## Install pre-commit hooks only
	@pre-commit install
	@pre-commit install --hook-type commit-msg
	@echo "$(GREEN)✓$(NC) Hooks installed"

#──────────────────────────────────────────────────────────────────────────────
# Code Quality
#──────────────────────────────────────────────────────────────────────────────

lint: ## Run linter (ruff) on source code
	@echo "$(BLUE)Running ruff linter...$(NC)"
	@ruff check $(SRC)

lint-fix: ## Run linter and auto-fix issues
	@echo "$(BLUE)Running ruff linter with auto-fix...$(NC)"
	@ruff check --fix $(SRC)

format: ## Format code with ruff
	@echo "$(BLUE)Formatting code with ruff...$(NC)"
	@ruff format $(SRC)

format-check: ## Check code formatting without changes
	@echo "$(BLUE)Checking code format...$(NC)"
	@ruff format --check $(SRC)

type: ## Run type checker (ty)
	@echo "$(BLUE)Running ty type checker...$(NC)"
	@ty check $(SRC) || echo "$(YELLOW)⚠$(NC) ty not installed or failed (it's still in alpha)"

check: ## Run all checks (lint, format, type)
	@echo "$(BLUE)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(NC)"
	@echo "$(BLUE)  Running all checks$(NC)"
	@echo "$(BLUE)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(NC)"
	@$(MAKE) --no-print-directory lint
	@$(MAKE) --no-print-directory format-check
	@$(MAKE) --no-print-directory type
	@echo "$(GREEN)✓$(NC) All checks passed"

pre-commit: ## Run all pre-commit hooks
	@echo "$(BLUE)Running pre-commit hooks...$(NC)"
	@pre-commit run --all-files

#──────────────────────────────────────────────────────────────────────────────
# Testing
#──────────────────────────────────────────────────────────────────────────────

test: ## Run all tests with coverage
	@echo "$(BLUE)Running tests...$(NC)"
	@pytest tests/ -v --cov=custom_components.chameleon --cov-report=term-missing

test-quick: ## Run tests without coverage (faster)
	@echo "$(BLUE)Running tests (quick mode)...$(NC)"
	@pytest tests/ -v

test-watch: ## Run tests in watch mode (requires pytest-watch)
	@echo "$(BLUE)Running tests in watch mode...$(NC)"
	@ptw tests/ -- -v

#──────────────────────────────────────────────────────────────────────────────
# YAML Linting
#──────────────────────────────────────────────────────────────────────────────

yaml-lint: ## Lint YAML files
	@echo "$(BLUE)Linting YAML files...$(NC)"
	@yamllint -c .yamllint.yml .

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
	@echo "$(GREEN)✓$(NC) Cleaned"

clean-all: clean ## Clean everything including venv
	@rm -rf .venv
	@echo "$(GREEN)✓$(NC) Cleaned all (including venv)"

#──────────────────────────────────────────────────────────────────────────────
# Development Server
#──────────────────────────────────────────────────────────────────────────────

dev-setup: ## Setup development environment and start dev server
	@echo "$(BLUE)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(NC)"
	@echo "$(BLUE)  Setting up Chameleon development environment$(NC)"
	@echo "$(BLUE)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(NC)"
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
	@echo "$(GREEN)✓$(NC) Deployed. Restart Home Assistant to apply changes."

#──────────────────────────────────────────────────────────────────────────────
# Help
#──────────────────────────────────────────────────────────────────────────────

help: ## Show this help message
	@echo ""
	@echo "$(BLUE)Chameleon - Home Assistant Integration$(NC)"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-15s$(NC) %s\n", $$1, $$2}'
	@echo ""

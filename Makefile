# Makefile for Chameleon Home Assistant Integration
# Run 'make help' to see available commands

.DEFAULT_GOAL := help
.PHONY: help setup lint format check type clean install-hooks

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
# Development (Docker targets will be added later)
#──────────────────────────────────────────────────────────────────────────────

# Placeholder for future Docker targets
# docker-build: ## Build Home Assistant dev container
# docker-run: ## Run Home Assistant dev container
# docker-logs: ## View container logs
# docker-stop: ## Stop container

#──────────────────────────────────────────────────────────────────────────────
# Deployment
#──────────────────────────────────────────────────────────────────────────────

# Example rsync deployment (customize REMOTE_HOST)
# REMOTE_HOST := homelab
# REMOTE_PATH := /config/custom_components/chameleon

# deploy: ## Deploy to production HA server via rsync
# 	@echo "$(BLUE)Deploying to $(REMOTE_HOST)...$(NC)"
# 	@rsync -avz --delete $(SRC)/ $(REMOTE_HOST):$(REMOTE_PATH)/
# 	@echo "$(GREEN)✓$(NC) Deployed. Restart Home Assistant to apply changes."

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

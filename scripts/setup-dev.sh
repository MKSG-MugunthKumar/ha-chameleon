#!/usr/bin/env bash
# Setup development environment for Chameleon Home Assistant Integration
# Usage: ./scripts/setup-dev.sh

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored output
info() { echo -e "${BLUE}ℹ${NC} $1"; }
success() { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; }

# Check if a command exists
command_exists() {
    command -v "$1" &> /dev/null
}

# Header
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Chameleon - Development Environment Setup${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Check for uv
check_uv() {
    if command_exists uv; then
        success "uv is installed ($(uv --version))"
        return 0
    else
        warn "uv is not installed"
        info "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        # Source the env to get uv in path
        export PATH="$HOME/.local/bin:$PATH"
        if command_exists uv; then
            success "uv installed successfully"
            return 0
        else
            error "Failed to install uv. Please install manually: https://docs.astral.sh/uv/"
            return 1
        fi
    fi
}

# Install development tools via uv
install_dev_tools() {
    info "Installing development tools..."

    # Install pre-commit
    if command_exists pre-commit; then
        success "pre-commit is already installed"
    else
        info "Installing pre-commit..."
        uv tool install pre-commit
        success "pre-commit installed"
    fi

    # Install ruff
    if command_exists ruff; then
        success "ruff is already installed"
    else
        info "Installing ruff..."
        uv tool install ruff
        success "ruff installed"
    fi

    # Install ty (optional, still in alpha)
    if command_exists ty; then
        success "ty is already installed"
    else
        info "Installing ty (Astral type checker - alpha)..."
        if uv tool install ty 2>/dev/null; then
            success "ty installed"
        else
            warn "ty installation failed (it's still in alpha, this is expected)"
            warn "You can try manually: uv tool install ty --prerelease=allow"
        fi
    fi
}

# Setup pre-commit hooks
setup_precommit() {
    info "Setting up pre-commit hooks..."

    # Install pre-commit hooks
    pre-commit install
    success "pre-commit hooks installed"

    # Install commit-msg hook for conventional commits
    pre-commit install --hook-type commit-msg
    success "commit-msg hook installed"
}

# Create virtual environment for testing (optional)
setup_venv() {
    if [[ -d ".venv" ]]; then
        success "Virtual environment already exists"
    else
        info "Creating virtual environment..."
        uv venv
        success "Virtual environment created at .venv/"
    fi

    info "Installing development dependencies..."
    uv pip install -e ".[dev]" 2>/dev/null || {
        # Fallback if editable install fails (no src layout)
        uv pip install pre-commit ruff homeassistant-stubs
    }
    success "Development dependencies installed"
}

# Verify setup
verify_setup() {
    echo ""
    info "Verifying setup..."

    local all_good=true

    if command_exists pre-commit; then
        success "pre-commit: $(pre-commit --version)"
    else
        error "pre-commit not found"
        all_good=false
    fi

    if command_exists ruff; then
        success "ruff: $(ruff --version)"
    else
        error "ruff not found"
        all_good=false
    fi

    if command_exists ty; then
        success "ty: $(ty --version 2>/dev/null || echo 'installed')"
    else
        warn "ty not installed (optional)"
    fi

    if [[ -f ".git/hooks/pre-commit" ]]; then
        success "pre-commit hook installed"
    else
        error "pre-commit hook not installed"
        all_good=false
    fi

    if [[ -f ".git/hooks/commit-msg" ]]; then
        success "commit-msg hook installed"
    else
        warn "commit-msg hook not installed"
    fi

    echo ""
    if $all_good; then
        success "Development environment is ready!"
    else
        error "Some components are missing. Please check the errors above."
        return 1
    fi
}

# Print next steps
print_next_steps() {
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}  Setup Complete!${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Run linting:        make lint"
    echo "  2. Run formatting:     make format"
    echo "  3. Run all checks:     make check"
    echo "  4. See all commands:   make help"
    echo ""
    echo "Commit message format (conventional commits):"
    echo "  feat(chameleon): add new feature"
    echo "  fix(chameleon): fix a bug"
    echo "  docs(chameleon): update documentation"
    echo ""
}

# Main
main() {
    cd "$(dirname "$0")/.." || exit 1

    check_uv || exit 1
    install_dev_tools
    setup_precommit
    # setup_venv  # Uncomment if you want a venv
    verify_setup
    print_next_steps
}

main "$@"

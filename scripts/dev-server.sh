#!/usr/bin/env bash
# Development server management for Chameleon
# Usage: ./scripts/dev-server.sh [command]
#
# Commands:
#   start     - Start the Home Assistant dev server
#   stop      - Stop the dev server
#   restart   - Restart the dev server (reload code changes)
#   logs      - Show container logs (follow mode)
#   shell     - Open a shell in the container
#   status    - Show server status
#   clean     - Stop server and remove all data
#   validate  - Validate integration code
#   test-lint - Run linting on integration code
#   help      - Show this help message

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${BLUE}ℹ${NC} $1"; }
success() { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; }

# Project root
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
CONTAINER_NAME="ha-chameleon-dev"
CONFIG_DIR="$PROJECT_DIR/ha-dev-config"
IMAGE_DIR="$CONFIG_DIR/www/chameleon"

# Check docker
check_docker() {
    if ! command -v docker &> /dev/null; then
        error "Docker is not installed. Please install Docker first."
        exit 1
    fi

    if ! docker info &> /dev/null; then
        error "Docker daemon is not running. Please start Docker first."
        exit 1
    fi
}

# Ensure required directories exist
ensure_directories() {
    mkdir -p "$IMAGE_DIR"

    # Create sample configuration.yaml if it doesn't exist
    if [[ ! -f "$CONFIG_DIR/configuration.yaml" ]]; then
        info "Creating default configuration.yaml..."
        cat > "$CONFIG_DIR/configuration.yaml" << 'EOF'
# Home Assistant Development Configuration
# For Chameleon integration testing

default_config:

# Enable demo platform for test lights
demo:

logger:
  default: info
  logs:
    custom_components.chameleon: debug
EOF
        success "Created configuration.yaml"
    fi
}

# Start the dev server
start_server() {
    info "Starting Home Assistant dev server..."

    ensure_directories

    docker compose -f "$COMPOSE_FILE" up -d

    success "Home Assistant dev server started!"
    echo ""
    echo "  Access Home Assistant at: ${GREEN}http://localhost:8123${NC}"
    echo "  First-time setup: Create an account when prompted"
    echo ""
    echo "  Available test lights (demo platform):"
    echo "    - light.bed_light"
    echo "    - light.ceiling_lights"
    echo "    - light.kitchen_lights"
    echo ""
    echo "  Add images to: ${BLUE}ha-dev-config/www/chameleon/${NC}"
    echo ""
    info "Waiting for Home Assistant to start..."
    echo "  Check logs with: ${YELLOW}./scripts/dev-server.sh logs${NC}"
    echo "  Or use:          ${YELLOW}make dev-logs${NC}"
}

# Stop the dev server
stop_server() {
    info "Stopping Home Assistant dev server..."
    docker compose -f "$COMPOSE_FILE" down
    success "Home Assistant dev server stopped"
}

# Restart the dev server (useful after code changes)
restart_server() {
    info "Restarting Home Assistant dev server..."
    docker compose -f "$COMPOSE_FILE" restart
    success "Home Assistant dev server restarted"
    echo ""
    info "Changes to custom_components will be loaded"
    echo "  View logs: ${YELLOW}./scripts/dev-server.sh logs${NC}"
}

# Show logs
show_logs() {
    info "Showing Home Assistant logs (Ctrl+C to exit)..."
    docker compose -f "$COMPOSE_FILE" logs -f
}

# Open shell in container
open_shell() {
    info "Opening shell in Home Assistant container..."
    docker exec -it "$CONTAINER_NAME" bash
}

# Show status
show_status() {
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        success "Home Assistant dev server is running"
        echo "  Container: $CONTAINER_NAME"
        echo "  URL: http://localhost:8123"
        echo ""
        echo "  Quick commands:"
        echo "    Logs:    ${YELLOW}make dev-logs${NC}"
        echo "    Shell:   ${YELLOW}make dev-shell${NC}"
        echo "    Restart: ${YELLOW}make dev-restart${NC}"
    else
        warn "Home Assistant dev server is not running"
        echo "  Start with: ${YELLOW}make dev-start${NC}"
        echo "  Or:         ${YELLOW}./scripts/dev-server.sh start${NC}"
    fi
}

# Clean everything (stop and remove data)
clean_server() {
    warn "This will stop the server and remove all development data!"
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        info "Stopping server..."
        docker compose -f "$COMPOSE_FILE" down -v 2>/dev/null || true

        info "Removing development data..."
        rm -rf "$CONFIG_DIR"

        success "Development environment cleaned"
        echo "  Run '${YELLOW}make dev-start${NC}' to start fresh"
    else
        info "Cancelled"
    fi
}

# Validate integration code
validate_code() {
    info "Validating Chameleon integration..."

    # Check if container is running
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        error "Dev server is not running. Start it first with: make dev-start"
        exit 1
    fi

    # Run Home Assistant config check
    info "Running Home Assistant config validation..."
    if docker exec "$CONTAINER_NAME" python -m homeassistant --script check_config -c /config; then
        success "Configuration valid"
    else
        error "Configuration validation failed"
        exit 1
    fi
}

# Run linting on integration code
test_lint() {
    info "Running linter on integration code..."

    if command -v ruff &> /dev/null; then
        ruff check "$PROJECT_DIR/custom_components/chameleon"
        success "Linting passed"
    else
        warn "ruff not installed. Install with: pip install ruff"
        exit 1
    fi
}

# Print usage
print_usage() {
    echo ""
    echo "  ${BLUE}Chameleon Development Server${NC}"
    echo ""
    echo "  Usage: $0 [command]"
    echo ""
    echo "  ${GREEN}Server Commands:${NC}"
    echo "    start       Start the Home Assistant dev server"
    echo "    stop        Stop the dev server"
    echo "    restart     Restart the dev server (reload code changes)"
    echo "    logs        Show container logs (follow mode)"
    echo "    shell       Open a shell in the container"
    echo "    status      Show server status"
    echo "    clean       Stop server and remove all data"
    echo ""
    echo "  ${GREEN}Development Commands:${NC}"
    echo "    validate    Validate integration configuration"
    echo "    test-lint   Run linting on integration code"
    echo ""
    echo "  ${GREEN}Makefile Shortcuts:${NC}"
    echo "    make dev-setup    Setup and start dev environment"
    echo "    make dev-start    Start the dev server"
    echo "    make dev-stop     Stop the dev server"
    echo "    make dev-restart  Restart after code changes"
    echo "    make dev-logs     View server logs"
    echo "    make dev-shell    Open shell in container"
    echo "    make dev-status   Check server status"
    echo ""
    echo "  ${GREEN}Examples:${NC}"
    echo "    $0 start        # Start dev server"
    echo "    $0 restart      # Reload after code changes"
    echo "    $0 logs         # View logs"
    echo "    $0 clean        # Reset everything"
    echo ""
}

# Main
main() {
    check_docker

    case "${1:-help}" in
        start)
            start_server
            ;;
        stop)
            stop_server
            ;;
        restart)
            restart_server
            ;;
        logs)
            show_logs
            ;;
        shell)
            open_shell
            ;;
        status)
            show_status
            ;;
        clean)
            clean_server
            ;;
        validate)
            validate_code
            ;;
        test-lint)
            test_lint
            ;;
        help|--help|-h)
            print_usage
            ;;
        *)
            error "Unknown command: $1"
            print_usage
            exit 1
            ;;
    esac
}

main "$@"

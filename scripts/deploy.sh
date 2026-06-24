#!/usr/bin/env bash
# ============================================================
# Build & Deploy Script for InvestingAssistant
# ============================================================
# Usage:
#   ./scripts/deploy.sh              # Build layer + frontend, deploy all stacks
#   ./scripts/deploy.sh --layer      # Rebuild Lambda layer only
#   ./scripts/deploy.sh --frontend   # Rebuild frontend only
#   ./scripts/deploy.sh --deploy     # Deploy without rebuilding
#   ./scripts/deploy.sh --stack Api  # Deploy a specific stack
# ============================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAYER_DIR="$PROJECT_ROOT/build/lambda-layer"
LAYER_REQS="$PROJECT_ROOT/build/lambda-layer-requirements.txt"
FRONTEND_DIR="$PROJECT_ROOT/src/frontend"
INFRA_DIR="$PROJECT_ROOT/infrastructure"
VENV_DIR="$PROJECT_ROOT/.venv"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${BLUE}[deploy]${NC} $1"; }
ok()   { echo -e "${GREEN}[  ok  ]${NC} $1"; }
warn() { echo -e "${YELLOW}[ warn ]${NC} $1"; }
err()  { echo -e "${RED}[error]${NC} $1"; }

# ---------------------------------------------------------------
# Build Lambda Layer
# ---------------------------------------------------------------
build_layer() {
    log "Building Lambda layer from $LAYER_REQS ..."

    # Clean old layer
    rm -rf "$LAYER_DIR/python"
    mkdir -p "$LAYER_DIR/python"

    # Install for Lambda (Linux x86_64, Python 3.12)
    pip install \
        --target "$LAYER_DIR/python" \
        --platform manylinux2014_x86_64 \
        --only-binary=:all: \
        --implementation cp \
        --python-version 3.12 \
        --upgrade \
        -r "$LAYER_REQS" \
        --quiet

    LAYER_SIZE=$(du -sh "$LAYER_DIR" | cut -f1)
    ok "Lambda layer built ($LAYER_SIZE)"
}

# ---------------------------------------------------------------
# Build Frontend
# ---------------------------------------------------------------
build_frontend() {
    log "Building frontend ..."
    cd "$FRONTEND_DIR"
    npm run build --silent
    DIST_SIZE=$(du -sh "$FRONTEND_DIR/dist" | cut -f1)
    ok "Frontend built ($DIST_SIZE)"
    cd "$PROJECT_ROOT"
}

# ---------------------------------------------------------------
# CDK Deploy
# ---------------------------------------------------------------
deploy() {
    local stack_arg="${1:-}"

    log "Deploying via CDK ..."

    # Activate venv for CDK
    export VIRTUAL_ENV="$VENV_DIR"
    export PATH="$VENV_DIR/bin:$PATH"

    cd "$INFRA_DIR"

    if [ -n "$stack_arg" ]; then
        log "Deploying stack: InvestingAssistant-$stack_arg"
        cdk deploy "InvestingAssistant-$stack_arg" --require-approval never
    else
        log "Deploying all stacks ..."
        cdk deploy --all --require-approval never
    fi

    ok "Deployment complete!"
    cd "$PROJECT_ROOT"
}

# ---------------------------------------------------------------
# Main
# ---------------------------------------------------------------
main() {
    cd "$PROJECT_ROOT"

    # Parse args
    local do_layer=false
    local do_frontend=false
    local do_deploy=false
    local stack=""

    if [ $# -eq 0 ]; then
        # No args = full build + deploy
        do_layer=true
        do_frontend=true
        do_deploy=true
    fi

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --layer)    do_layer=true ;;
            --frontend) do_frontend=true ;;
            --deploy)   do_deploy=true ;;
            --stack)    do_deploy=true; stack="${2:-}"; shift ;;
            --all)      do_layer=true; do_frontend=true; do_deploy=true ;;
            *)          err "Unknown arg: $1"; exit 1 ;;
        esac
        shift
    done

    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║   InvestingAssistant Deploy Pipeline     ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
    echo ""

    if $do_layer; then
        build_layer
    fi

    if $do_frontend; then
        build_frontend
    fi

    if $do_deploy; then
        deploy "$stack"
    fi

    echo ""
    ok "All done! 🚀"
}

main "$@"

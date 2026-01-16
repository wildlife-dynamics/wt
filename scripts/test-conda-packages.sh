#!/bin/bash
set -euo pipefail

# Test conda packages built by build-conda-packages.sh
# Usage: ./scripts/test-conda-packages.sh [--skip-install]
#
# This script:
# 1. Creates a fresh test environment using the local conda channel
# 2. Installs all wt-* packages from the channel
# 3. Adds test dependencies
# 4. Runs unit tests for each package against the installed packages

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
CHANNEL_DIR="${WT_CONDA_CHANNEL:-/tmp/wt-conda-channel}"
TEST_DIR="${WT_TEST_DIR:-/tmp/wt-conda-test}"

# All packages to test
PACKAGES=(
    "wt-contracts"
    "wt-registry"
    "wt-task"
    "wt-compiler"
    "wt-invokers"
    "wt-runner"
)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Verify channel exists and is indexed
verify_channel() {
    log_info "Verifying channel at $CHANNEL_DIR"

    if [[ ! -d "$CHANNEL_DIR" ]]; then
        log_error "Channel directory not found: $CHANNEL_DIR"
        log_error "Run ./scripts/build-conda-packages.sh first"
        return 1
    fi

    if [[ ! -f "$CHANNEL_DIR/noarch/repodata.json" ]]; then
        log_error "Channel not indexed (repodata.json missing)"
        log_error "Run: rattler-index fs $CHANNEL_DIR"
        return 1
    fi

    # Check that all packages exist in channel
    for pkg in "${PACKAGES[@]}"; do
        if ! ls "$CHANNEL_DIR/noarch/${pkg}-"*.conda &>/dev/null; then
            log_error "Package $pkg not found in channel"
            return 1
        fi
    done

    log_info "Channel verified: all packages present"
}

# Setup test environment
setup_test_env() {
    log_info "Setting up test environment at $TEST_DIR"

    # Clean up existing test directory
    rm -rf "$TEST_DIR"
    mkdir -p "$TEST_DIR"

    cd "$TEST_DIR"

    # Initialize pixi project with local channel first
    pixi init \
        --channel "file://$CHANNEL_DIR" \
        --channel conda-forge

    log_info "Test environment initialized"
}

# Install all packages
install_packages() {
    log_info "Installing wt-* packages from local channel"

    cd "$TEST_DIR"

    # Install all packages
    pixi add "${PACKAGES[@]}"

    log_info "All packages installed"
}

# Install test dependencies
install_test_deps() {
    log_info "Installing test dependencies"

    cd "$TEST_DIR"

    # Add test dependencies
    pixi add pytest pytest-cov pytest-asyncio httpx

    log_info "Test dependencies installed"
}

# Run tests for a single package
run_package_tests() {
    local pkg="$1"
    local pkg_test_dir="$REPO_ROOT/$pkg/tests"

    log_info "Running tests for $pkg"

    if [[ ! -d "$pkg_test_dir" ]]; then
        log_warn "No tests directory found for $pkg, skipping"
        return 0
    fi

    cd "$TEST_DIR"

    # Run pytest for this package's tests
    if pixi run pytest "$pkg_test_dir" -v --tb=short; then
        log_info "Tests passed for $pkg"
        return 0
    else
        log_error "Tests FAILED for $pkg"
        return 1
    fi
}

# Run all tests
run_all_tests() {
    local failed=()

    log_info "Running tests for all packages"
    echo ""

    for pkg in "${PACKAGES[@]}"; do
        echo "=========================================="
        echo "  Testing: $pkg"
        echo "=========================================="

        if ! run_package_tests "$pkg"; then
            failed+=("$pkg")
        fi
        echo ""
    done

    if [[ ${#failed[@]} -gt 0 ]]; then
        log_error "Tests FAILED for: ${failed[*]}"
        return 1
    fi

    log_info "All tests passed!"
}

# Main execution
main() {
    local skip_install=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --skip-install)
                skip_install=true
                shift
                ;;
            *)
                log_error "Unknown argument: $1"
                exit 1
                ;;
        esac
    done

    echo "=========================================="
    echo "  wt Conda Package Test Suite"
    echo "=========================================="
    echo ""
    echo "Channel: $CHANNEL_DIR"
    echo "Test dir: $TEST_DIR"
    echo ""

    # Verify channel
    verify_channel

    if [[ "$skip_install" == false ]]; then
        # Setup and install
        setup_test_env
        install_packages
        install_test_deps
    else
        log_info "Skipping installation (--skip-install)"
        if [[ ! -d "$TEST_DIR" ]]; then
            log_error "Test directory not found. Run without --skip-install first."
            exit 1
        fi
    fi

    echo ""
    echo "=========================================="
    echo "  Running Unit Tests"
    echo "=========================================="
    echo ""

    # Run tests
    run_all_tests

    echo ""
    echo "=========================================="
    echo "  Test Suite Complete!"
    echo "=========================================="
}

main "$@"

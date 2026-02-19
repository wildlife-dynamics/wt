#!/bin/bash
set -euo pipefail

# Build conda packages for all wt packages using pixi build
# Usage: ./scripts/build-conda-packages.sh [package-name]
#
# If no package name provided, builds all packages in dependency order with parallelization:
#   Phase 1: wt-contracts (foundation)
#   Phase 2: wt-registry, wt-task, wt-task-gcp, wt-compiler, wt-invokers, wt-invokers-gcp (parallel)
#   Phase 3: wt-runner, wt-runner-gcp (depends on wt-invokers)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="${WT_CONDA_CHANNEL:-/tmp/wt-conda-channel}"

# Package groups for parallel building
PHASE1_PACKAGES=("wt-contracts")
PHASE2_PACKAGES=("wt-registry" "wt-task" "wt-task-gcp" "wt-compiler" "wt-invokers" "wt-invokers-gcp")
PHASE3_PACKAGES=("wt-runner" "wt-runner-gcp")

# All packages in build order (for single package builds)
ALL_PACKAGES=(
    "wt-contracts"
    "wt-registry"
    "wt-task"
    "wt-task-gcp"
    "wt-compiler"
    "wt-invokers"
    "wt-invokers-gcp"
    "wt-runner"
    "wt-runner-gcp"
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

# Clean pixi build caches to prevent stale packages
# pixi-build-python only tracks pyproject.toml for cache invalidation,
# not source code changes, so we must invalidate caches ourselves
clean_build_caches() {
    log_info "Cleaning pixi build caches to prevent stale packages"
    rm -rf "$REPO_ROOT/.pixi/build/pkgs-v0"
    rm -rf "$REPO_ROOT/.pixi/build/metadata-v0"
    rm -rf "$REPO_ROOT/.pixi/build/work"
}

# Function to extract version from git tag
get_version() {
    local pkg="$1"

    # Use Python script for version extraction
    if [[ -f "$SCRIPT_DIR/get-package-version.py" ]]; then
        python3 "$SCRIPT_DIR/get-package-version.py" "$pkg"
    else
        # Fallback: extract from git tags directly
        local tag
        tag=$(git -C "$REPO_ROOT" tag -l "${pkg}/v*" --sort=-version:refname 2>/dev/null | head -n1)

        if [[ -n "$tag" ]]; then
            # Extract version from tag (e.g., wt-contracts/v1.0.0 -> 1.0.0)
            echo "${tag#${pkg}/v}"
        else
            # Fallback to development version
            echo "0.1.0.dev0"
        fi
    fi
}

# Function to build a single package
build_package() {
    local pkg="$1"
    local pkg_dir="$REPO_ROOT/$pkg"
    local version
    version=$(get_version "$pkg")

    log_info "Building $pkg version $version"

    # Verify package directory exists
    if [[ ! -d "$pkg_dir" ]]; then
        log_error "Package directory not found: $pkg_dir"
        return 1
    fi

    # Set version for setuptools-scm
    export SETUPTOOLS_SCM_PRETEND_VERSION="$version"

    # Build the package
    if ! pixi build \
        --clean \
        --path "$pkg_dir/pyproject.toml" \
        --output-dir "$OUTPUT_DIR"; then
        log_error "Failed to build $pkg"
        return 1
    fi

    # Move noarch packages to the noarch subdirectory
    # pixi build puts packages at the root of output-dir, but conda channels
    # expect packages in platform-specific subdirectories
    for conda_file in "$OUTPUT_DIR"/*.conda; do
        if [[ -f "$conda_file" ]]; then
            local filename
            filename=$(basename "$conda_file")
            log_info "Moving $filename to noarch/"
            mv "$conda_file" "$OUTPUT_DIR/noarch/"
        fi
    done

    log_info "Successfully built $pkg"
}

# Function to index the channel
index_channel() {
    log_info "Indexing channel at $OUTPUT_DIR"

    if ! command -v rattler-index &> /dev/null; then
        log_error "rattler-index not found. Run 'pixi install' from repo root to install dependencies."
        return 1
    fi

    rattler-index fs "$OUTPUT_DIR"
    log_info "Channel indexed"
}

# Function to build packages in parallel
build_parallel() {
    local -a packages=("$@")
    local -a pids=()
    local -a failed=()

    log_info "Building ${#packages[@]} packages in parallel: ${packages[*]}"

    for pkg in "${packages[@]}"; do
        build_package "$pkg" &
        pids+=($!)
    done

    # Wait for all builds and collect failures
    for i in "${!pids[@]}"; do
        if ! wait "${pids[$i]}"; then
            failed+=("${packages[$i]}")
        fi
    done

    if [[ ${#failed[@]} -gt 0 ]]; then
        log_error "Failed to build packages: ${failed[*]}"
        return 1
    fi

    log_info "All parallel builds completed successfully"
}

# Function to setup output directory
setup_output_dir() {
    log_info "Setting up output directory: $OUTPUT_DIR"
    mkdir -p "$OUTPUT_DIR/noarch"
    mkdir -p "$OUTPUT_DIR/linux-64"
    mkdir -p "$OUTPUT_DIR/osx-arm64"
    mkdir -p "$OUTPUT_DIR/osx-64"
    # Clean old packages to prevent stale artifacts
    rm -f "$OUTPUT_DIR/noarch"/*.conda
}

# Main execution
main() {
    local target_pkg="${1:-}"

    echo "=========================================="
    echo "  wt Conda Package Builder"
    echo "=========================================="
    echo ""

    # Setup output directory
    setup_output_dir

    # Clean pixi build caches before building
    clean_build_caches

    if [[ -n "$target_pkg" ]]; then
        # Build single package
        if [[ ! -d "$REPO_ROOT/$target_pkg" ]]; then
            log_error "Package $target_pkg not found"
            exit 1
        fi

        log_info "Building single package: $target_pkg"
        build_package "$target_pkg"
        index_channel
    else
        # Build all packages in phases with parallelization
        log_info "Building all packages in 3 phases"
        echo ""

        # Phase 1: Build foundation package (wt-contracts)
        echo "=========================================="
        echo "  Phase 1: Foundation (wt-contracts)"
        echo "=========================================="
        for pkg in "${PHASE1_PACKAGES[@]}"; do
            build_package "$pkg"
        done
        index_channel
        echo ""

        # Phase 2: Build packages that depend only on wt-contracts (parallel)
        echo "=========================================="
        echo "  Phase 2: Parallel Build"
        echo "=========================================="
        build_parallel "${PHASE2_PACKAGES[@]}"
        index_channel
        echo ""

        # Phase 3: Build packages with multiple dependencies (wt-runner)
        echo "=========================================="
        echo "  Phase 3: Final (wt-runner, wt-runner-gcp)"
        echo "=========================================="
        for pkg in "${PHASE3_PACKAGES[@]}"; do
            build_package "$pkg"
        done
        index_channel
    fi

    echo ""
    echo "=========================================="
    echo "  Build Complete!"
    echo "=========================================="
    echo ""
    echo "Channel location: $OUTPUT_DIR"
    echo ""
    echo "To use this channel, add to your pixi.toml:"
    echo "  channels = [\"file://$OUTPUT_DIR\", \"conda-forge\"]"
    echo ""
    echo "Or install packages directly:"
    echo "  pixi add --channel file://$OUTPUT_DIR wt-contracts"
}

main "$@"

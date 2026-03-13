#!/bin/bash
set -euo pipefail

# Idempotent sync of all wt packages to PyPI and prefix.dev conda channel.
# For each package, checks the latest git tag version, queries each registry,
# and publishes anything missing. Safe to run multiple times.
#
# Usage: ./scripts/sync-registries.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# GCP metapackages are conda-only (no PyPI publish)
GCP_PACKAGES=("wt-task-gcp" "wt-invokers-gcp" "wt-runner-gcp")

# Build order (same phases as build-conda-packages.sh)
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

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

is_gcp_package() {
    local pkg="$1"
    for gcp in "${GCP_PACKAGES[@]}"; do
        [[ "$pkg" == "$gcp" ]] && return 0
    done
    return 1
}

check_pypi() {
    local pkg="$1" version="$2"
    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" "https://pypi.org/pypi/${pkg}/${version}/json")
    [[ "$status" == "200" ]]
}

publish_pypi() {
    local pkg="$1"
    log_info "Building and publishing $pkg to PyPI"
    (cd "$REPO_ROOT/$pkg" && uv build && uv publish)
}

publish_conda() {
    local pkg="$1"
    log_info "Building and uploading $pkg to prefix.dev"
    "$SCRIPT_DIR/build-conda-packages.sh" "$pkg"
    rattler-build upload prefix \
        -c ecoscope-workflows \
        /tmp/wt-conda-channel/noarch/"${pkg}"-*.conda
}

main() {
    echo "=========================================="
    echo "  wt Registry Sync"
    echo "=========================================="
    echo ""

    local any_published=false

    for pkg in "${ALL_PACKAGES[@]}"; do
        local version
        version=$(python3 "$SCRIPT_DIR/get-package-version.py" "$pkg")

        if [[ "$version" == "0.1.0" ]]; then
            # Check if this is the fallback (no tag exists)
            local tag_count
            tag_count=$(git -C "$REPO_ROOT" tag -l "${pkg}/v*" 2>/dev/null | wc -l)
            if [[ "$tag_count" -eq 0 ]]; then
                log_warn "$pkg: no tags found, skipping"
                continue
            fi
        fi

        log_info "$pkg v$version — checking registries"

        # Check and publish to PyPI (skip GCP metapackages)
        if ! is_gcp_package "$pkg"; then
            if check_pypi "$pkg" "$version"; then
                log_info "  PyPI: already published"
            else
                log_warn "  PyPI: MISSING — publishing"
                publish_pypi "$pkg"
                any_published=true
            fi
        else
            log_info "  PyPI: skipped (GCP metapackage)"
        fi

        # Always publish to conda (idempotent — prefix.dev rejects duplicates gracefully)
        log_info "  Conda: uploading (idempotent)"
        publish_conda "$pkg"
        any_published=true
    done

    echo ""
    echo "=========================================="
    echo "  Sync Complete"
    echo "=========================================="

    if [[ "$any_published" == "true" ]]; then
        log_info "Some packages were published or re-uploaded"
    else
        log_info "All packages already in sync"
    fi
}

main "$@"

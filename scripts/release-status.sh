#!/bin/bash
set -euo pipefail

# Gather release status for all wt packages
# Shows which packages have changed since their last release tag,
# with commit logs and diffs to help determine version bumps.
#
# Usage: ./scripts/release-status.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

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

# Hardcoded dependency graph (parsing TOML in bash is fragile; graph rarely changes)
print_dependency_graph() {
    echo "=== DEPENDENCY GRAPH ==="
    echo "wt-contracts: (none)"
    echo "wt-registry: wt-contracts"
    echo "wt-task: wt-contracts"
    echo "wt-compiler: wt-contracts"
    echo "wt-invokers: wt-contracts"
    echo "wt-runner: wt-contracts, wt-invokers"
    echo "wt-task-gcp: wt-task"
    echo "wt-invokers-gcp: wt-invokers"
    echo "wt-runner-gcp: wt-runner, wt-invokers-gcp"
    echo "=== END DEPENDENCY GRAPH ==="
}

# Get release status for a single package
package_status() {
    local pkg="$1"
    local pkg_dir="$REPO_ROOT/$pkg"

    # Convert package name for directory (wt-contracts -> wt-contracts/)
    echo "=== PACKAGE: $pkg ==="

    # Verify package directory exists
    if [[ ! -d "$pkg_dir" ]]; then
        echo "DIRECTORY: NOT FOUND"
        echo "=== END PACKAGE: $pkg ==="
        return
    fi

    # Find latest tag
    local latest_tag
    latest_tag=$(git -C "$REPO_ROOT" tag -l "${pkg}/v*" --sort=-version:refname 2>/dev/null | head -n1)

    if [[ -n "$latest_tag" ]]; then
        local current_version="${latest_tag#${pkg}/v}"
        echo "LATEST_TAG: $latest_tag"
        echo "CURRENT_VERSION: $current_version"

        # Check for commits since last tag
        local commit_count
        commit_count=$(git -C "$REPO_ROOT" log "${latest_tag}..HEAD" --oneline -- "${pkg_dir}/" 2>/dev/null | wc -l | tr -d ' ')

        if [[ "$commit_count" -gt 0 ]]; then
            echo "HAS_CHANGES: YES"
            echo "COMMIT_COUNT: $commit_count"

            echo "--- COMMIT LOG ---"
            git -C "$REPO_ROOT" log "${latest_tag}..HEAD" --oneline -- "${pkg_dir}/"
            echo "--- END COMMIT LOG ---"

            echo "--- DIFF STAT ---"
            git -C "$REPO_ROOT" diff "${latest_tag}..HEAD" --stat -- "${pkg_dir}/"
            echo "--- END DIFF STAT ---"

            echo "--- DIFF ---"
            git -C "$REPO_ROOT" diff "${latest_tag}..HEAD" -- "${pkg_dir}/" | head -200 || true
            echo "--- END DIFF ---"
        else
            echo "HAS_CHANGES: NO"
        fi
    else
        echo "LATEST_TAG: NONE"
        echo "CURRENT_VERSION: NONE"

        # No tag — diff from initial commit
        local initial_commit
        initial_commit=$(git -C "$REPO_ROOT" rev-list --max-parents=0 HEAD 2>/dev/null | head -n1)

        local commit_count
        commit_count=$(git -C "$REPO_ROOT" log "${initial_commit}..HEAD" --oneline -- "${pkg_dir}/" 2>/dev/null | wc -l | tr -d ' ')

        if [[ "$commit_count" -gt 0 ]]; then
            echo "HAS_CHANGES: YES (never tagged)"
            echo "COMMIT_COUNT: $commit_count"

            echo "--- COMMIT LOG ---"
            git -C "$REPO_ROOT" log "${initial_commit}..HEAD" --oneline -- "${pkg_dir}/"
            echo "--- END COMMIT LOG ---"

            echo "--- DIFF STAT ---"
            git -C "$REPO_ROOT" diff "${initial_commit}..HEAD" --stat -- "${pkg_dir}/"
            echo "--- END DIFF STAT ---"

            echo "--- DIFF ---"
            git -C "$REPO_ROOT" diff "${initial_commit}..HEAD" -- "${pkg_dir}/" | head -200 || true
            echo "--- END DIFF ---"
        else
            echo "HAS_CHANGES: NO"
        fi
    fi

    echo "=== END PACKAGE: $pkg ==="
    echo ""
}

# Main execution
main() {
    echo "=========================================="
    echo "  wt Release Status"
    echo "=========================================="
    echo ""

    log_info "Scanning all packages for changes since last release..."
    echo ""

    # Print dependency graph first
    print_dependency_graph
    echo ""

    # Process each package
    for pkg in "${ALL_PACKAGES[@]}"; do
        package_status "$pkg"
    done

    echo "=========================================="
    echo "  Scan Complete"
    echo "=========================================="
}

main "$@"

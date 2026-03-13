#!/bin/bash
set -euo pipefail

# Create an annotated git tag for a wt package release.
#
# Usage: ./scripts/release-tag.sh [-f <notes-file>] <package-name> <version>
# Example: ./scripts/release-tag.sh -f release-notes.md wt-contracts 0.2.0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

VALID_PACKAGES=(
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

# Validate package name
validate_package() {
    local pkg="$1"
    for valid in "${VALID_PACKAGES[@]}"; do
        if [[ "$pkg" == "$valid" ]]; then
            return 0
        fi
    done
    return 1
}

# Validate version format (X.Y.Z)
validate_version() {
    local version="$1"
    if [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        return 0
    fi
    return 1
}

main() {
    local notes_file=""
    while getopts ":f:" opt; do
        case $opt in
            f) notes_file="$OPTARG" ;;
            \?) log_error "Unknown option: -$OPTARG"; exit 1 ;;
            :) log_error "Option -$OPTARG requires an argument"; exit 1 ;;
        esac
    done
    shift $((OPTIND - 1))

    if [[ $# -ne 2 ]]; then
        echo "Usage: $0 [-f <notes-file>] <package-name> <version>"
        echo "Example: $0 -f release-notes.md wt-contracts 0.2.0"
        echo ""
        echo "Valid packages:"
        for pkg in "${VALID_PACKAGES[@]}"; do
            echo "  $pkg"
        done
        exit 1
    fi

    local pkg="$1"
    local version="$2"
    local tag="${pkg}/v${version}"

    # Validate package name
    if ! validate_package "$pkg"; then
        log_error "Unknown package: $pkg"
        echo "Valid packages:"
        for valid in "${VALID_PACKAGES[@]}"; do
            echo "  $valid"
        done
        exit 1
    fi

    # Validate version format
    if ! validate_version "$version"; then
        log_error "Invalid version format: $version (expected X.Y.Z)"
        exit 1
    fi

    # Check tag doesn't already exist
    if git -C "$REPO_ROOT" rev-parse "$tag" &>/dev/null; then
        log_error "Tag already exists: $tag"
        exit 1
    fi

    # Read release notes: -f file takes priority, then stdin pipe, then empty.
    local notes=""
    if [[ -n "$notes_file" ]]; then
        if [[ ! -r "$notes_file" ]]; then
            log_error "Cannot read notes file: $notes_file"
            exit 1
        fi
        notes="$(cat "$notes_file")"
    elif [[ ! -t 0 ]] && read -t 0; then
        notes="$(cat)"
    fi

    # Create annotated tag
    log_info "Creating tag: $tag"
    if [[ -n "$notes" ]]; then
        _RELEASE_TAG_TMPFILE="$(mktemp)"
        trap 'rm -f "$_RELEASE_TAG_TMPFILE"' EXIT
        printf '%s v%s\n\n%s\n' "$pkg" "$version" "$notes" > "$_RELEASE_TAG_TMPFILE"
        git -C "$REPO_ROOT" tag -a "$tag" -F "$_RELEASE_TAG_TMPFILE"
    else
        git -C "$REPO_ROOT" tag -a "$tag" -m "$pkg v$version"
    fi

    log_info "Successfully created tag: $tag"
    echo ""
    log_warn "Tag is local only. To trigger the PyPI publish workflow, push with:"
    echo "  git push origin $tag"
}

main "$@"

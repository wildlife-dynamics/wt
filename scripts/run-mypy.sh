#!/bin/bash
# Run mypy across all wt-* packages
# Exits with failure if any package has type errors

packages=(wt-contracts wt-registry wt-task wt-compiler wt-invokers wt-runner)
failed=0

for pkg in "${packages[@]}"; do
    if [ -d "$pkg" ]; then
        # Convert wt-foo to wt_foo for the source path
        src_name="${pkg//-/_}"
        echo "Checking $pkg..."
        (cd "$pkg" && uv run mypy "src/$src_name") || failed=1
    fi
done

exit $failed

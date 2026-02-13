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
        # wt-runner requires Python >=3.13; all other packages use 3.12
        if [ "$pkg" = "wt-runner" ]; then
            python_version="3.13"
        else
            python_version="3.12"
        fi
        (cd "$pkg" && uv run --python "$python_version" --all-extras mypy "src/$src_name") || failed=1
    fi
done

exit $failed

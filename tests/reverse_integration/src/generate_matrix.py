#!/usr/bin/env python3
"""Generate GitHub Actions matrix from manifest.yaml.

This script outputs a JSON object suitable for use with GitHub Actions'
`strategy.matrix` and `fromJson()` function.

Usage:
    python generate_matrix.py

Output format:
    {"include": [{"id": "events@main", "name": "events @ main"}, ...]}
"""

from __future__ import annotations

import json

from conftest import get_repo_configs, load_manifest


def generate_matrix() -> dict[str, list[dict[str, str]]]:
    """Generate matrix entries for all repo×ref combinations.

    Returns:
        Dict with "include" key containing list of matrix entries.
        Each entry has "id" (for --manifest-item) and "name" (for job display).
    """
    manifest = load_manifest()
    refs = ["main", "latest-release"]

    entries = []
    configs = get_repo_configs(manifest)
    for config in configs:
        entries.append({
            "id": config.id,
            "name": config.id.replace("@", " @ "),
        })

    return {"include": entries}


def main() -> None:
    """Print matrix JSON to stdout."""
    matrix = generate_matrix()
    print(json.dumps(matrix))


if __name__ == "__main__":
    main()

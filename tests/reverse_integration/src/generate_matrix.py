#!/usr/bin/env python3
"""Generate GitHub Actions matrix from manifest.yaml.

This script outputs a JSON object suitable for use with GitHub Actions'
`strategy.matrix` and `fromJson()` function.

Usage:
    python generate_matrix.py

Output format:
    {"include": [
        {"id": "events@main", "name": "events @ main", "tests": ["recompile"]},
        ...
    ]}
"""

from __future__ import annotations

import json
from typing import Any

from conftest import get_repo_configs, load_manifest


def generate_matrix() -> dict[str, list[dict[str, Any]]]:
    """Generate matrix entries for all repo x ref combinations.

    Returns:
        Dict with "include" key containing list of matrix entries. Each
        entry has ``id`` (for ``--manifest-item``), ``name`` (for job
        display), and ``tests`` (the per-item test scope, used by the
        workflow to gate the generated-tests step).
    """
    manifest = load_manifest()
    configs = get_repo_configs(manifest)
    entries = [
        {
            "id": config.id,
            "name": config.id.replace("@", " @ "),
            "tests": list(config.tests),
        }
        for config in configs
    ]
    return {"include": entries}


def main() -> None:
    """Print matrix JSON to stdout."""
    matrix = generate_matrix()
    print(json.dumps(matrix))


if __name__ == "__main__":
    main()

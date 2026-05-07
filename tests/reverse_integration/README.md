# Reverse Integration Tests

This test suite validates that changes to the `wt-compiler` don't break downstream workflow implementations.

## Quick Start

```bash
cd tests/reverse_integration

# Install dependencies
uv sync --all-extras --dev

# Run all tests
uv run pytest

# Run only recompilation tests (faster, no pixi required)
uv run pytest src/test_recompile.py -v
```

## Test Types

- **Recompilation tests** (`test_recompile.py`): Clone downstream repos, recompile with latest `wt-compiler`, and verify only expected files change
- **Generated tests** (`test_generated.py`): Run the generated workflow's test suite via `pixi`

## Local-source overrides

The harness invokes `wt-compiler` with
`--env-overrides=wt-compiler-env-overrides.toml` (resolved relative to
`manifest.yaml`). That file ships path-source declarations resolving to
the local monorepo via `../..`-relative paths, so every `wt-*` import in
both the discovery env and the compiled package's envs resolves to the
local checkout — never to a released conda or PyPI package. See
[Env Overrides](../../docs/content/reference/env-overrides.md) for the
full file format.

## CLI Options

| Option | Description |
|--------|-------------|
| `--manifest-item ID` | Test a specific manifest item by ID (e.g., `events@main`) |
| `--repo-url URL` | Test a single repo (overrides manifest) |
| `--repo-ref REF` | Override git ref (`main`, `v1.0.0`, `latest-release`) |
| `--repo-auth token:TOKEN` | Auth token for private repos |
| `--cases case1,case2` | Run specific test cases only |
| `--skip-generated-tests` | Skip pixi-based generated tests |

## Examples

```bash
# Test a specific manifest item (used by CI matrix jobs)
uv run pytest src/test_recompile.py -v --manifest-item=events@main

# Test against a specific version
uv run pytest src/test_recompile.py -v --repo-ref=v1.0.0

# Test against latest release tag
uv run pytest -v --repo-ref=latest-release

# Run specific test cases
uv run pytest src/test_generated.py -v --cases=example-case

# Test a private repo
uv run pytest -v --repo-url=https://github.com/org/private-repo --repo-auth=token:ghp_xxx
```

### Manifest Item IDs

Each repo in the manifest gets an ID in the format `{repo-name}@{ref}`:
- `events@main` - the "events" repo at ref "main"
- `events@latest-release` - the "events" repo at the latest release tag

For monorepos with multiple specs, the ID includes the spec name:
- `workflows-monorepo/etl@main` - the "etl" spec in "workflows-monorepo"

## Configuration

Edit `manifest.yaml` to add/modify downstream repos:

```yaml
repos:
  - url: https://github.com/org/repo
    ref: main                    # optional, default: main
    spec_path: spec.yaml         # optional, default: spec.yaml
    generated_path: wf-my-workflow  # path to generated package

diff_allowlist:
  - README.md
  - pixi.lock
  - VERSION.yaml
```

## CI Integration

Tests run automatically on:
- Push to `main`
- PRs with the `run-reverse-integration` label

The CI workflow uses a **dynamic matrix** generated from `manifest.yaml`:
1. The `generate-matrix` job reads the manifest and outputs matrix entries
2. Each repo×ref combination runs as a parallel job (e.g., "events @ main", "events @ latest-release")
3. Job names in the GitHub Checks UI match the manifest item IDs

To generate the matrix locally:
```bash
uv run python src/generate_matrix.py
# Output: {"include": [{"id": "events@main", "name": "events @ main"}, ...]}
```

See `.github/workflows/reverse-integration.yml` for details.

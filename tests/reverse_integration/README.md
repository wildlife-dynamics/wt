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
[Injected Dependencies](../../docs/content/reference/wt-compiler.md#injected-dependencies)
for the full file format.

## CLI Options

| Option | Description |
|--------|-------------|
| `--manifest-item ID` | Test a specific manifest item by ID (e.g., `events@main`) |
| `--repo-url URL` | Test a single repo (overrides manifest) |
| `--repo-ref REF` | Override git ref (`main`, `v1.0.0`, `latest-release`) |
| `--repo-auth token:TOKEN` | Auth token for private repos |
| `--cases case1,case2` | Run specific test cases only |

To skip generated tests for a manifest item, omit `generated` from its
`tests` list — there is no CLI flag to override this. Test scope is a
manifest concept enforced by the CI workflow's matrix.

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

If a manifest entry sets `compile_flags.env_overrides`, its ID gets a
`:env-overrides` suffix automatically (e.g., `events@main:env-overrides`).
This lets the same repo appear twice in the matrix — once compile-only,
once with overrides — without colliding.

## Configuration

Edit `manifest.yaml` to add/modify downstream repos. Each entry must
declare its own `tests` (subset of `recompile`, `generated`) and
`diff_allowlist`. There is no inheritance from a top-level allowlist.

```yaml
repos:
  - url: https://github.com/org/repo
    ref: main                    # optional, default: main
    spec_path: spec.yaml         # optional, default: spec.yaml
    generated_path: wf-my-workflow  # path to generated package
    tests: [recompile]           # required: which test files to run in CI
    diff_allowlist:              # required: per-item allowlist
      - README.md
      - pixi.lock
      - file: VERSION.yaml
        allowed_variance:
          - 'MIN: \d+'
```

Allowlist entries may be plain strings (file basename — any change
allowed) or conditional dicts with `file` and `allowed_variance` regex
patterns (only regions matching the patterns may differ). See
`src/helpers/diff.py` for the variance-check semantics.

The `tests` field controls which CI step runs for this matrix item.
Compile-only items list `[recompile]`; items that should additionally
exercise `pixi install` and the generated test suite list
`[recompile, generated]`. Locally, the `tests` field is advisory —
running `pytest src/test_generated.py` against a compile-only item
will execute it ad-hoc.

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
# Output: {"include": [
#   {"id": "events@main", "name": "events @ main", "tests": ["recompile"]},
#   {"id": "events@main:env-overrides", "name": "events @ main:env-overrides",
#    "tests": ["recompile", "generated"]},
#   ...
# ]}
```

The CI workflow gates the generated-tests step on
`contains(matrix.tests, 'generated')`, so compile-only matrix entries
show as a skipped step in the GitHub Actions UI rather than running
pytest just to see internal skips.

See `.github/workflows/reverse-integration.yml` for details.

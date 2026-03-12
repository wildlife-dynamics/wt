# wt
Workflow template engine with support for web-form configuration, parallel operators, and flexible execution targets.

## Architecture

For package architecture diagrams, dependency graphs, and development guidelines, see [CLAUDE.md](CLAUDE.md).

## Releasing Packages

Releases are managed via git tags and automated PyPI publishing.

### Overview

1. Run `bash scripts/release-status.sh` to see which packages have unreleased changes
2. Determine the appropriate version bump for each changed package:
   - **Patch** (0.x.Y → 0.x.Y+1): bugfixes, docs, internal refactors, dependency updates with no API changes
   - **Minor** (0.X.y → 0.X+1.0): new features or breaking changes (pre-1.0 convention)
3. Create tags with `bash scripts/release-tag.sh <package-name> <version>` (tags use format `<package-name>/v<version>`)
4. Push tags **one at a time**: `git push origin <tag>`

### Constraints

- **One tag per push**: The publish workflow (`.github/workflows/publish.yml`) reads `GITHUB_REF` to determine which package to build. Pushing multiple tags in a single `git push` will only trigger one workflow run, so the other packages won't be published. Always push one tag at a time.
- **Cross-package dependencies**: If an upstream package has breaking changes, check whether downstream dependents need their dependency floor bumped and a patch release.
- **GCP metapackages** (`wt-task-gcp`, `wt-invokers-gcp`, `wt-runner-gcp`) only need releasing when their dependency pins change.

### Using Claude Code

Run `/release` in Claude Code to get an interactive assistant that walks through the full process — analyzing changes, recommending versions, creating tags, and pushing them with confirmation at each step.

## Pre-commit Hooks

### Mypy

The mypy hook addresses common pitfalls with type checking in pre-commit ([reference](https://jaredkhan.com/blog/mypy-pre-commit)):

| Problem | Solution |
|---------|----------|
| Checking only changed files misses errors in dependent code | `pass_filenames: false` runs mypy on all packages |
| Pre-commit's isolated virtualenv lacks project dependencies | `language: system` uses the dev environment via `uv` |
| Default hooks use `--ignore-missing-imports` hiding errors | Uses per-package strict configs in `pyproject.toml` |

Run manually: `./scripts/run-mypy.sh`

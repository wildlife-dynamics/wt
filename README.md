# wt
Workflow template engine with support for web-form configuration, parallel operators, and flexible execution targets.

## Architecture

For package architecture diagrams, dependency graphs, and development guidelines, see [CLAUDE.md](CLAUDE.md).

## Workmux

For development, if you choose to use [`workmux`](https://workmux.raine.dev/) with the container sandbox,
a custom `Dockerfile.sandbox` is provided here for convenience. To use it, please refer to the building
and configuration docs here: https://workmux.raine.dev/guide/sandbox/container#custom-images. 

## Pre-commit Hooks

### Mypy

The mypy hook addresses common pitfalls with type checking in pre-commit ([reference](https://jaredkhan.com/blog/mypy-pre-commit)):

| Problem | Solution |
|---------|----------|
| Checking only changed files misses errors in dependent code | `pass_filenames: false` runs mypy on all packages |
| Pre-commit's isolated virtualenv lacks project dependencies | `language: system` uses the dev environment via `uv` |
| Default hooks use `--ignore-missing-imports` hiding errors | Uses per-package strict configs in `pyproject.toml` |

Run manually: `./scripts/run-mypy.sh`

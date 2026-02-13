# wt
Workflow template engine with support for web-form configuration, parallel operators, and flexible execution targets.

## Pre-commit Hooks

### Mypy

The mypy hook addresses common pitfalls with type checking in pre-commit ([reference](https://jaredkhan.com/blog/mypy-pre-commit)):

| Problem | Solution |
|---------|----------|
| Checking only changed files misses errors in dependent code | `pass_filenames: false` runs mypy on all packages |
| Pre-commit's isolated virtualenv lacks project dependencies | `language: system` uses the dev environment via `uv` |
| Default hooks use `--ignore-missing-imports` hiding errors | Uses per-package strict configs in `pyproject.toml` |

Run manually: `./scripts/run-mypy.sh`

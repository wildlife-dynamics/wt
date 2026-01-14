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

## Testing

### Reverse Integration Tests

The [reverse integration test suite](tests/reverse_integration/README.md) validates that framework changes don't break downstream workflow implementations. See the linked README for usage instructions.

# Env Overrides

`wt-compiler` accepts an explicit per-feature override file that declares
conda and/or pypi dependencies to merge into the compiled package's
`pixi.toml`, plus an optional pseudo-feature interpreted only by the
compiler.

The override file is read by `wt-compiler` only — it is never handed to
`pixi`. Conventional filename: `wt-compiler-env-overrides.toml`.

## Purpose

The intended use is **development and testing of `wt` feature branches**:
forcing a compiled package's pixi.toml (and the wt-compiler discovery env)
to install `wt-*` siblings from a local monorepo checkout instead of from
released conda or PyPI packages. It should not be used in production.

## Flag

```bash
wt-compiler compile --spec spec.yaml \
    --env-overrides=PATH
```

`PATH` may be absolute or relative to the current working directory; the
CLI resolves it to absolute before parsing.

## Recognized features

| Feature | Where it lands | Notes |
|---------|----------------|-------|
| `default` | top-level `[dependencies]` and `[pypi-dependencies]` | Replaces any auto-injected entries with the same name. |
| `runner` | `[feature.runner.dependencies]` and `[feature.runner.pypi-dependencies]` | The compiled `test` env pulls runner via `features=["runner","test"]`, so cross-cutting wt-* overrides usually go here. |
| `test` | `[feature.test.dependencies]` and `[feature.test.pypi-dependencies]` | Reaches the compiled `test` env only. Use for test-env-only divergence. Typically empty. |
| `discovery` | wt-compiler discovery env only (never emitted into pixi.toml) | Pseudo-feature: deps are overlaid into the discovery env via `uv pip install --reinstall-package`. |

Any other feature name is rejected with a clear error.

## Section types

For every recognized feature, both of the following sections are
supported:

- `[feature.<name>.dependencies]` — conda deps. Map of package name →
  version string (e.g. `">=1.0,<2.0"`, `"*"`).
- `[feature.<name>.pypi-dependencies]` — pypi deps. Map of package name
  → pixi-style table (`{path = "..."}`, `{git = "...", tag = "..."}`,
  `{url = "..."}`, with optional `editable`, `extras`, `subdirectory`,
  `rev`, `branch`).

Bare-version shorthand (`foo = "*"`) is **not** supported in
`pypi-dependencies`; declare an explicit table instead.

## Path resolution

Relative `path` values inside the override file resolve against the
**override file's own directory**, matching pixi.toml semantics. The
compiler resolves all paths to absolute before emitting the compiled
pixi.toml or invoking `uv`.

## Replacement semantics

Per-package per-feature replacement: if the override file declares
`wt-task` in `feature.runner.pypi-dependencies`, `wt-compiler` suppresses
any auto-injection of `wt-task` (conda or pypi) for the runner feature.
Other auto-injected packages in the same feature are unaffected, and
`wt-task` in other features is unaffected.

For the discovery overlay specifically, when the override file and the
spec.yaml's `requirements:` both declare the same package name, **the
override wins** and a one-line warning is logged so the supersession is
discoverable in CI logs.

## Worked example

The reverse-integration harness ships its own override file at
`tests/reverse_integration/wt-compiler-env-overrides.toml`:

```toml
# Discovery env overlay (never emitted into the compiled pixi.toml).
# Forces the discovery env's wt-* sources to local.
[feature.discovery.pypi-dependencies]
wt-registry  = { path = "../../wt-registry",  editable = true }
wt-task      = { path = "../../wt-task",      editable = true }
wt-contracts = { path = "../../wt-contracts", editable = true }

# Default feature — emitted as top-level [pypi-dependencies] in pixi.toml.
[feature.default.pypi-dependencies]
wt-task      = { path = "../../wt-task",      editable = true, extras = ["gcp"] }
wt-contracts = { path = "../../wt-contracts", editable = true }
wt-registry  = { path = "../../wt-registry",  editable = true }

# Runner feature — emitted as [feature.runner.pypi-dependencies].
[feature.runner.pypi-dependencies]
wt-runner    = { path = "../../wt-runner",    editable = true, extras = ["gcp"] }
wt-task      = { path = "../../wt-task",      editable = true, extras = ["gcp"] }
wt-invokers  = { path = "../../wt-invokers",  editable = true, extras = ["gcp"] }
wt-contracts = { path = "../../wt-contracts", editable = true }
wt-registry  = { path = "../../wt-registry",  editable = true }
```

Because the file lives in `tests/reverse_integration/`, the
`../..`-relative paths resolve to the monorepo root.

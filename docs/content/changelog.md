# Changelog

## Unreleased

### `wt-compiler`

- **New:** `--env-overrides PATH` flag for `wt-compiler compile`. The file
  is a small pixi-style toml fragment that declares per-feature conda and
  pypi dependencies (recognized features: `default`, `runner`, `test`,
  `discovery`) which the compiler merges into the compiled `pixi.toml` and
  the discovery env. Intended for development and testing of `wt` feature
  branches. See [Env Overrides](reference/env-overrides.md).
- **New:** PyPI dependencies are now installed into the discovery env via
  a single bulk `uv pip install` call with `--reinstall-package` per
  requirement. This ensures all path/git/url sources resolve together and
  forces uv to replace any conda-installed `.dist-info` of the same name.
  `PyPIInstallError` now reports the full batch rather than a single
  requirement.
- **Breaking:** Removed the implicit "PyPI mode" auto-derivation that
  inferred sibling `wt-runner` / `wt-task` PyPI sources from
  `wt-registry`'s PEP 610 `direct_url.json`. The `wt_pypi_deps` parameter
  on `DagCompiler` and the `wt_pypi_deps` field on `DiscoveryResult` are
  removed. To pin specific sibling sources, declare them explicitly via
  `--env-overrides=…` — e.g. for a path source:

  ```toml
  [feature.default.pypi-dependencies]
  wt-task = { path = "/abs/path/to/wt-task", editable = true }
  ```

  Workflows whose specs previously relied on auto-derived siblings will,
  after this change, get whatever their dep tree resolves naturally
  (typically released-PyPI siblings).

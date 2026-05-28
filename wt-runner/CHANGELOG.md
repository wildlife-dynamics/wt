# Changelog

## v0.3.0 — 2026-05-28

- Add `GET /params` endpoint that returns the workflow's `params.json` by proxying the compiled CLI's new `get params` metadata attribute ([#178](https://github.com/wildlife-dynamics/wt/pull/178))

## v0.2.0 — 2026-05-13

- Register the new `SandboxInvoker` and `CloudRunJobsSandboxInvoker` in the `INVOKERS` dispatch map ([#164](https://github.com/wildlife-dynamics/wt/pull/164))
- Rewrite `_convert` to consume the compiled CLI's single-key envelope (`{"result": ...}` or `{"validation_errors": [...]}`), raising `wt_contracts.ValidationError` on schema-validation failure. Remove the obsolete `_is_422` helper ([#164](https://github.com/wildlife-dynamics/wt/pull/164))
- Standardize ruff lint config to enforce type annotations and Google-style docstrings ([#155](https://github.com/wildlife-dynamics/wt/pull/155))

## v0.1.5 — 2026-03-27

- Fix errant injection of `wt-task` into the wt-runner conda environment

## v0.1.4 — 2026-03-18

- Constrain Python to `<3.14` for ecoscope-eda-core compatibility
- Bundle ecoscope-eda-core transitive dependencies (`aiohttp`, `pydantic`, `stamina`) in `[gcp]` extras

## v0.1.3 — 2026-03-13

- Remove direct git reference from `wt-runner[gcp]` extras to fix PyPI publishing ([#71](https://github.com/wildlife-dynamics/wt/pull/71))

## v0.1.2 — 2026-03-13

- Bootstrap release for prefix.dev conda channel

## v0.1.1 — 2026-03-05

- Fix incorrect license metadata

## v0.1.0 — 2026-03-05

- Initial release

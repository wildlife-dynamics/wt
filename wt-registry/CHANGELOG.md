# Changelog

## v0.2.2 — 2026-05-13

- Standardize ruff lint config to enforce type annotations and Google-style docstrings; convert docstrings and example scripts accordingly ([#155](https://github.com/wildlife-dynamics/wt/pull/155))

## v0.2.1 — 2026-04-14

- Fix `SurfacesDescriptionSchema` to serialize `BaseModel` default values via `.model_dump()` instead of storing the raw model instance in the JSON schema

## v0.2.0 — 2026-03-13

- Add `auto_discover()` for entry-point-based task module discovery ([#60](https://github.com/wildlife-dynamics/wt/pull/60))
- CLI now auto-discovers task modules via `wt_registry` entry points before processing explicit `--package` args ([#60](https://github.com/wildlife-dynamics/wt/pull/60))

## v0.1.0 — 2026-03-05

- Initial release

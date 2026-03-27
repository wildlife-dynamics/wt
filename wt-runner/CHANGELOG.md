# Changelog

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

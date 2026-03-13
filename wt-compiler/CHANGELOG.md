# Changelog

## v0.2.0 — 2026-03-13

- Add PyPI dependency source: workflow specs can now declare PyPI requirements alongside conda packages
- Generalize compiled workflow ResponseModel to accept any result type (previously hardcoded to specific output types)
- Make Graphviz optional: skip graph.png generation with a warning when the `dot` binary is not found
- Add `pypi-dependencies` support to PixiToml and Feature artifact models

## v0.1.1 — 2026-03-05

- Fix incorrect license metadata

## v0.1.0 — 2026-03-05

- Initial release

# Changelog

## v0.2.0 — 2026-03-13

- Support PyPI dependencies (`git`/`path`/`url` sources) in workflow specs, emitted as `[pypi-dependencies]` in compiled `pixi.toml` ([#60](https://github.com/wildlife-dynamics/wt/pull/60))
- Generalize compiled `ResponseModel.result` from `DashboardJson | OutputFiles` to `Any`, removing hard dependency on `ecoscope_workflows_core` types ([#61](https://github.com/wildlife-dynamics/wt/pull/61))
- Make Graphviz graph generation best-effort — warns instead of failing when `dot` binary is unavailable ([#60](https://github.com/wildlife-dynamics/wt/pull/60))
- Add `wt_registry` entry-point auto-discovery to task discovery pipeline ([#60](https://github.com/wildlife-dynamics/wt/pull/60))

## v0.1.1 — 2026-03-05

- Fix incorrect license metadata

## v0.1.0 — 2026-03-05

- Initial release

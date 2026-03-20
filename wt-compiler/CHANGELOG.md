# Changelog

## v0.3.0 — 2026-03-19

- Add CI and Tag GitHub Actions workflow templates to the wizard scaffold ([#83](https://github.com/wildlife-dynamics/wt/pull/83))
- Add `.gitignore` template to the wizard scaffold ([#83](https://github.com/wildlife-dynamics/wt/pull/83))
- Add `linux-aarch64` platform support ([#83](https://github.com/wildlife-dynamics/wt/pull/83))
- Fix wizard template rendering for nested output paths ([#83](https://github.com/wildlife-dynamics/wt/pull/83))
- Pin compiled output version bounds for wt-task (`>=0.1.2`) and wt-runner (`>=0.1.4`) ([#96](https://github.com/wildlife-dynamics/wt/pull/96))
- Remove errant injection of wt-task into wt-runner conda environment ([#96](https://github.com/wildlife-dynamics/wt/pull/96))
- Pin `datamodel-code-generator` to `==0.42.1` ([#96](https://github.com/wildlife-dynamics/wt/pull/96))

## v0.2.0 — 2026-03-13

- Support PyPI dependencies (`git`/`path`/`url` sources) in workflow specs, emitted as `[pypi-dependencies]` in compiled `pixi.toml` ([#60](https://github.com/wildlife-dynamics/wt/pull/60))
- Generalize compiled `ResponseModel.result` from `DashboardJson | OutputFiles` to `Any`, removing hard dependency on `ecoscope_workflows_core` types ([#61](https://github.com/wildlife-dynamics/wt/pull/61))
- Make Graphviz graph generation best-effort — warns instead of failing when `dot` binary is unavailable ([#60](https://github.com/wildlife-dynamics/wt/pull/60))
- Add `wt_registry` entry-point auto-discovery to task discovery pipeline ([#60](https://github.com/wildlife-dynamics/wt/pull/60))

## v0.1.1 — 2026-03-05

- Fix incorrect license metadata

## v0.1.0 — 2026-03-05

- Initial release

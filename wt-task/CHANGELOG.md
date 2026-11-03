# Changelog

## v0.2.0 — 2026-11-03

- Add a content-addressed step cache: `.cached(CacheSpec)` keys a step's result on code identity, fixed inputs and upstream output digests. Identical calls share entries across workflows, and an unchanged output stops recomputation downstream ([#275](https://github.com/wildlife-dynamics/wt/pull/275))
- Add `CacheSettings` for runtime cache configuration (`WT_CACHE__*` env vars, `.env`, `pyproject.toml`): store, epoch, scope, io TTL, verify, strict ([#275](https://github.com/wildlife-dynamics/wt/pull/275))
- Each run writes a per-step cache report (`cache-report.json`), including how far a failed run got ([#275](https://github.com/wildlife-dynamics/wt/pull/275))
- New dependencies: `packaging` and `pydantic-settings`. Object-store backends need the new `cache` extra (`obstore`)
- Raise the `wt-contracts` floor to `>=0.3.0`

## v0.1.3 — 2026-05-13

- Standardize ruff lint config to enforce type annotations and Google-style docstrings; convert module/class/function docstrings accordingly ([#155](https://github.com/wildlife-dynamics/wt/pull/155))

## v0.1.2 — 2026-03-13

- `configure_tracer()` and `attach_context()` now warn instead of raising `ImportError` when tracing deps are missing ([#60](https://github.com/wildlife-dynamics/wt/pull/60))

## v0.1.1 — 2026-03-05

- Fix incorrect license metadata

## v0.1.0 — 2026-03-05

- Initial release

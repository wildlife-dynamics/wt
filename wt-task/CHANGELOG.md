# Changelog

## v0.3.0 — 2026-11-09

- Add opt-in lazy cache hits (`WT_CACHE__LAZY` / `CacheSettings.lazy`): inside a run scope a hit is served as a `LazyCachedValue` and its payload is read only when a step that runs consumes it, so a cached rerun no longer reads payloads for steps that also hit. A lazy hit whose payload is gone or unreadable fails the run with `CacheEvictedError` rather than recomputing, so enable it only where the store keeps payloads as long as keys ([#287](https://github.com/wildlife-dynamics/wt/pull/287))
- Export `materialize`, `LazyCachedValue` and `CacheEvictedError` from `wt_task.cache` ([#287](https://github.com/wildlife-dynamics/wt/pull/287))
- Cache report rows gain a `loaded` field: the wall time of reading a hit's payload, or null if nothing consumed it ([#287](https://github.com/wildlife-dynamics/wt/pull/287))

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

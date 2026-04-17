# Changelog

## Unreleased

- `AbstractInvoker.run()` and `.wait()` are now concrete wrappers enforcing an
  `IDLE → RUNNING → IDLE` lifecycle. Subclasses implement `_run`/`_wait` and
  may override `_pre_run`/`_post_run` hooks.
- Added `PixiUnpackMixin` and `UploadResultsArchiveMixin` for composable
  pre/post-run behaviour (pixi-pack env unpack + results archive upload).
- Added `SandboxInvoker` (composes both mixins) with a `wt-invokers.sandbox`
  console entry point; suitable for running inside sandboxed containers.
- Added `CloudRunJobsSandboxInvoker` (proxy) that triggers a pre-deployed
  Cloud Run Job whose container runs the sandbox CLI. Requires
  `pip install wt-invokers[cloud-run]`.

## v0.1.2 — 2026-03-13

- Bootstrap release for prefix.dev conda channel

## v0.1.1 — 2026-03-05

- Fix incorrect license metadata

## v0.1.0 — 2026-03-05

- Initial release

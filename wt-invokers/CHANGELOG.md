# Changelog

## v0.5.0 — 2026-06-18

- **Breaking:** `--environment-tar-digest sha256:<hex>` is now **required** on the sandbox CLI and as the `environment_tar_digest` keyword argument on `CloudRunJobsSandboxInvoker.run(...)`. The downloaded `environment.tar` is verified against this digest before unpacking; on mismatch the run **fails before unpacking, raising and exiting non-zero** (no `result.json` written), so a tampered or corrupted environment never executes. Callers populating `invoker_kwargs` for wt-runner must now include `environment_tar_digest` ([#196](https://github.com/wildlife-dynamics/wt/pull/196))

## v0.4.1 — 2026-06-15

- Follow HTTP redirects when downloading the environment tar, so a GitHub-release-style 302 to a signed asset URL is handled ([#193](https://github.com/wildlife-dynamics/wt/pull/193))

## v0.4.0 — 2026-06-11

- Add `--dangerously-skip-results-archive-upload` flag to the sandbox CLI, which skips the post-run results archive upload; requires `--results-url` to point at a real destination and is mutually exclusive with `--results-upload-url` ([#185](https://github.com/wildlife-dynamics/wt/pull/185))
- Add corresponding `skip_results_archive_upload` parameter to `CloudRunJobsSandboxInvoker`, with eager validation at job-submission time mirroring the sandbox CLI's rules ([#185](https://github.com/wildlife-dynamics/wt/pull/185))
- `results_upload_url` is now optional on `CloudRunJobsSandboxInvoker` and the sandbox CLI — required only when the results archive upload is not skipped ([#185](https://github.com/wildlife-dynamics/wt/pull/185))

## v0.3.0 — 2026-05-13

- Add `SandboxInvoker`: downloads a pixi-pack environment tarball, runs the workflow inside the unpacked env, and uploads a results archive to a signed URL. Exposed via the `wt-invokers.sandbox` console entry point as a Docker image ENTRYPOINT ([#164](https://github.com/wildlife-dynamics/wt/pull/164))
- Add `CloudRunJobsSandboxInvoker`: proxy that triggers a pre-deployed Cloud Run Job whose container runs the sandbox CLI ([#164](https://github.com/wildlife-dynamics/wt/pull/164))
- Refactor `AbstractInvoker.run()` / `wait()` into concrete lifecycle wrappers around `_pre_run` / `_run` / `_wait` / `_post_run` hooks, with an immutable `run_args` view and mutable `run_state` dict for hook-to-hook state sharing. Existing invokers internally renamed `run`→`_run` / `wait`→`_wait` — external call sites unchanged ([#164](https://github.com/wildlife-dynamics/wt/pull/164))
- Add `PixiUnpackMixin` (`_pre_run` hook: stamina-retried environment download + pixi-unpack) and `UploadResultsArchiveMixin` (`_post_run` hook: stream-PUT tar of results to signed URL, or copy to `file://` for tests) ([#164](https://github.com/wildlife-dynamics/wt/pull/164))
- Add `PixiUnpackError` wrapping `subprocess.CalledProcessError` with `returncode` / `stdout` / `stderr` ([#164](https://github.com/wildlife-dynamics/wt/pull/164))
- Add `publish-docker` CI job that builds and pushes the sandbox image on `wt-invokers/v*` tags after the conda package is available on prefix.dev ([#164](https://github.com/wildlife-dynamics/wt/pull/164))
- Standardize ruff lint config to enforce type annotations and Google-style docstrings ([#155](https://github.com/wildlife-dynamics/wt/pull/155))

## v0.2.0 — 2026-04-28

- Add optional `network`, `subnetwork`, and `no_external_ip` kwargs to `CloudBatchInvoker` for routing batch VMs through a specific VPC and egressing via Cloud NAT ([#143](https://github.com/wildlife-dynamics/wt/pull/143))

## v0.1.2 — 2026-03-13

- Bootstrap release for prefix.dev conda channel

## v0.1.1 — 2026-03-05

- Fix incorrect license metadata

## v0.1.0 — 2026-03-05

- Initial release

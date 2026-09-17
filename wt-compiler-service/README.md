# wt-compiler-service

A hot-registry FastAPI service that compiles workflow specs into DAGs on the
fly. It discovers tasks **in-process once** at startup (paying the heavy
task-stack import — e.g. `ecoscope.platform` — a single time), then serves many
`POST /compile` requests against the resident registry with **no subprocess, no
dependency solve, and no re-import**. Warm compiles complete in tens of
milliseconds.

This is the "compile in the service" component of the on-the-fly invoker
design: a trusted image bakes in the `wt` stack + the task libraries and serves
this app to turn specs into runnable DAGs cheaply. It complements
`wt_invokers.CompileFromEnvInvoker`, which does the same compilation as a
one-shot rather than a warm service.

## API

| Route | Description |
|-------|-------------|
| `GET /` | Health: `status` (`hot`/`cold`), `n_tasks_registered`, one-time `warmup_seconds`. |
| `POST /compile` | Body: exactly one of `spec` (object) or `spec_yaml` (string), plus optional `variant`, `pkg_name_prefix`. Compiles to a **persistent package on disk** and returns a **`build_id`**, the rendered `dag`, its `params_schema`, `release_name`/`package_name`, `compile_ms`, and `cached`. |
| `POST /run` | Body: `params` plus **exactly one of** `build_id` (run a build already on disk), `spec`, or `spec_yaml` (hot-compile then run); plus optional `execution_mode` (`sequential`), `mock_io`, `variant`, `pkg_name_prefix`, `env`, `timeout`, `results_url`. Returns the workflow envelope (`result`/`error`/`trace`) plus `build_id`, `results_url`, `compile_ms`, `run_ms`, `returncode`, `cached`. |

### Compile / run split

The flow is split around a **persistent on-disk build**:

- `/compile` compiles a spec to a package on disk (in-process, hot) and returns
  a `build_id`. Builds live under `WT_COMPILER_SERVICE__BUILD_ROOT` (default a
  temp subdir), keyed by a content hash, and are cached by content.
- `/run` runs a build — either an existing `build_id` (**no recompile**) or a
  `spec`/`spec_yaml` to hot-compile and then run. Execution **invokes the
  compiled package's CLI as a subprocess** (`python -m <package>.cli run`) via
  `wt_invokers.CompiledPackageInvoker`, in the same shared environment.

Running as a subprocess keeps each workflow **isolated** from the service — a
hung or crashing run is a killable child, not a fault in the compile server — at
the cost of the child cold-importing the task stack. Task-level failures come
back as `error` with a `200`; only compilation/validation failures return `400`
(and an unknown `build_id` returns `404`). Non-`mock_io` runs read
data-connection secrets from `env`. Results are returned inline for local
(`file://`) stores and persisted at any provided `results_url`.

> Note: the `build_id` registry is process-local — a build is addressable for
> the life of the serving process.

## Running

The service needs `wt-compiler`, `wt-registry`, and the **task libraries**
installed in the same environment (that is the whole point — the registry is
warmed in-process). Because `/run` executes `python -m <pkg>.cli` **in this same
shared env** (no per-workflow install), the env must *also* carry everything a
compiled workflow imports at runtime — `obstore`, `click`, `wt-task[-gcp]`, and
`opentelemetry-api` — mirroring a compiled workflow's own `[dependencies]`.
(Missing `obstore` is the usual symptom: `No module named obstore` at run time.)
See [`deploy/pixi.toml`](deploy/pixi.toml) for the baked "invoker" environment
used to validate it:

```sh
cd deploy
pixi install --locked      # provision the frozen env (ecoscope.platform + wt stack + this service)
pixi run serve             # warms in ~4s, then serves on :8099
```

Then:

```sh
curl localhost:8099/                       # {"status":"hot", "n_tasks_registered": 239, ...}
curl -X POST localhost:8099/compile \
  -H 'content-type: application/json' \
  -d '{"spec_yaml":"<your spec>", "variant":"gcp", "pkg_name_prefix":"ecoscope-workflows"}'
```

## Measured (real events workflow, 51 tasks)

- **Warmup:** ~3.9s once at startup (the `ecoscope.platform` import + 239-task discovery).
- **Compile:** ~77ms warm — versus ~6.7s for a cold `wt-compiler --from-env` subprocess, which re-imports the stack every call.

## Notes

- **Versioning.** Each compile stamps the build's `VERSION.yaml` and returns a
  `version`, tracked per workflow id in a small registry under
  `<BUILD_ROOT>/.versions/`: a **major** bump when the workflow's parameter
  schema changes, a **minor** bump otherwise (first compile → `0.1.0`). This is
  the `dump --update` bump logic **without** its pixi.lock carry-over — the
  service runs in a shared env and has no per-workflow lock to carry.
- **Results env var.** The compiled CLI reads its results URL from an env var
  and the invoker *sets* it; they must agree. The service sources one value from
  **`WT_INVOKERS__RESULTS_ENV_VAR`** (default `WT_RESULTS`) and threads it through
  *both* compile and run, so they can't diverge. For ecoscope/proxy deploys set
  `WT_INVOKERS__RESULTS_ENV_VAR=ECOSCOPE_WORKFLOWS_RESULTS` (the `deploy/pixi.toml`
  does this via `[activation.env]`). Symptom of a mismatch: the run fails with
  `Environment variable <NAME> is required`.
- The package depends on `wt-compiler` + `wt-registry` + `fastapi`; it does **not**
  depend on any specific task library. The tasks are supplied by the deployment
  environment (like `wt-runner` does not depend on specific workflows).
- `ecoscope-platform` currently pins `pydantic <2.9`, so `wt-compiler` must stay
  importable under 2.8.x. A CI guard that imports `wt_compiler` under the task
  stack's pinned pydantic is recommended to prevent regressions.

# Run a Workflow Locally

This guide covers the different ways to run a compiled workflow on your local
machine.

---

## Prerequisites

- A compiled workflow directory (produced by `wt-compiler compile`)
- [pixi](https://pixi.sh) installed

---

## Via the generated CLI

The most common way to run a workflow locally. Install dependencies first:

```bash
cd wt-my-workflow/
pixi install
```

### Pass parameters as JSON

```bash
pixi run workflow run --config-json '{"step_id": {"param": "value"}}'
```

### Pass parameters from a YAML file

```bash
pixi run workflow run --config-file config.yaml
```

The YAML file maps task instance IDs to their parameters:

```yaml
step_one:
  count: 10
step_two:
  threshold: 0.5
```

Only user-facing parameters appear here — arguments wired to other task outputs
via `${{ }}` references are resolved automatically at runtime.

### Select execution mode

```bash
pixi run workflow run --config-file config.yaml --execution-mode sequential
```

Currently only `sequential` is supported (the default).

### Run with mock I/O

Replace tasks tagged `io` with mock functions that return pre-loaded test data:

```bash
pixi run workflow run --config-file config.yaml --mock-io
```

This is useful for testing workflows without network access or external service
dependencies.

---

## Via wt-runner (FastAPI server)

For HTTP-based execution, use the `runner` pixi environment:

```bash
pixi run -e runner start
```

This starts a FastAPI server (default port 8080). Trigger the workflow:

```bash
curl -X POST http://localhost:8080/workflow \
  -H "Content-Type: application/json" \
  -d '{"params": {"step_one": {"count": 10}}}'
```

The server uses `LocalSubprocessInvoker` by default, which runs the workflow
CLI in a subprocess. See the
[wt-runner reference](../reference/wt-runner/index.md) for configuration
options and the
[wt-invokers reference](../reference/wt-invokers/index.md) for available
execution backends.

---

## Checking output

Both execution paths produce a JSON response conforming to the `ResponseModel`:

```json
{
  "result": { ... },
  "error": null,
  "trace": null
}
```

On success, `result` contains the workflow output. On failure, `error` contains
the exception message and `trace` contains the full traceback.

---

## OpenTelemetry tracing

The generated CLI supports OpenTelemetry tracing for debugging and
observability:

```bash
pixi run workflow run --config-file config.yaml --otel-exporter console
```

This prints trace spans to stdout. Use `--otel-exporter gcp` for Google Cloud
Trace export, or `--otel-exporter disabled` to turn tracing off (the default).

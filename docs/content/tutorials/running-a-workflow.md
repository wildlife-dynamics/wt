# Running a Workflow

In this tutorial you will run the compiled workflow from the previous tutorial,
pass parameters to it, and inspect the JSON output.

Previous: [Building Your First Workflow](first-workflow.md)

!!! note "Prerequisites"
    This tutorial assumes you have:

    - Completed the [Building Your First Workflow](first-workflow.md) tutorial
      and have a compiled workflow directory (e.g. `wt-double-and-sum/`).
    - [pixi](https://pixi.sh) installed. Compiled workflows are pixi projects
      and require pixi to run. See
      [Tooling & Prerequisites](../concepts/tooling.md) for install guidance.

---

## Step 1 -- Install the workflow dependencies

Navigate into the compiled workflow directory and install all dependencies:

```bash
cd wt-double-and-sum
pixi install
```

This reads the `pixi.toml` and creates a locked environment with all the
packages your workflow needs. You only need to do this once (or after
re-compiling with updated dependencies).

---

## Step 2 -- Run the workflow via the generated CLI

The compiled workflow includes a Click-based CLI entry point. pixi defines
a `run` task in the `pixi.toml` that invokes it. You can run the workflow
by passing parameters as a JSON string:

```bash
pixi run workflow run --config-json '{"numbers": {"count": 5}}'
```

Or create a YAML config file:

```yaml title="config.yaml"
numbers:
  count: 5
```

And pass it with `--config-file`:

```bash
pixi run workflow run --config-file config.yaml
```

### Understanding the parameter structure

The parameter keys correspond to **task instance IDs** from your `spec.yaml`.
Only parameters that are *not* wired to other task outputs appear here.

!!! tip "Web form generation"
    The same parameter schemas that drive the CLI also power auto-generated web
    forms via [React JSON Schema Form (RJSF)](https://rjsf-team.github.io/react-jsonschema-form/).
    You can customize how parameters appear in the form by using
    `typing.Annotated` with `pydantic.Field` in your registered functions — see
    the [JSON schema generation](registering-tasks.md#7-json-schema-generation)
    section of the registration tutorial for details.

In our
workflow:

- `numbers.count` is the only user-facing parameter — it controls how many
  numbers `generate_numbers` produces.
- `doubled` and `total` have no user-facing parameters because their inputs
  come from other task outputs via `${{ }}` references.

You can inspect the full parameter schema in `wt_double_and_sum/params.json`.

---

## Step 3 -- Inspect the output

The workflow prints a JSON result to stdout. For our example with `count: 5`,
the output will look like:

```json
{
  "result": 20
}
```

The result is `20` because: `generate_numbers(5)` produces `[0, 1, 2, 3, 4]`,
`double_number` maps over each to produce `[0, 2, 4, 6, 8]`, and
`sum_numbers` returns `0 + 2 + 4 + 6 + 8 = 20`.

The response is wrapped in a `ResponseModel` that also includes `error` and
`trace` fields when something goes wrong, making it easy to handle both
success and failure cases programmatically.

---

## Step 4 -- Run with mock I/O (optional)

If your workflow includes tasks tagged with `io` (e.g. API calls, file reads),
the compiler generates a mock variant that replaces those tasks with
pre-loaded test data. You can activate it with `--mock-io`:

```bash
pixi run workflow run --config-json '{"numbers": {"count": 5}}' --mock-io
```

Our simple numeric workflow has no I/O tasks, so mock mode behaves identically
to normal mode here. But for real-world workflows that call external APIs, this
is invaluable for testing without network access.

---

## Step 5 -- A taste of wt-runner (server-based execution)

For production use, workflows are typically executed through `wt-runner`, a
FastAPI server that accepts parameters as JSON over HTTP. The compiled workflow
includes a `runner` pixi environment pre-configured for this:

```bash
pixi run -e runner start
```

This starts the FastAPI server. You can then trigger the workflow via HTTP:

```bash
curl -X POST http://localhost:8080/workflow \
  -H "Content-Type: application/json" \
  -d '{"params": {"numbers": {"count": 5}}}'
```

The server returns the same JSON response model, but can also dispatch work
to different backends (local subprocess, Cloud Batch) depending on
configuration. See the [wt-runner reference](../reference/wt-runner/index.md)
and [wt-invokers reference](../reference/wt-invokers/index.md) for details.

---

## Summary

In this tutorial you learned how to:

- Install a compiled workflow's dependencies with `pixi install`
- Run the workflow via the generated CLI with JSON or YAML parameters
- Understand the parameter structure and how it maps to task instance IDs
- Inspect the JSON output
- Use mock I/O mode for testing
- Start the wt-runner FastAPI server for HTTP-based execution

## Next steps

- [Run a Workflow Locally](../how-to/run-workflow-locally.md) — concise
  how-to guide covering additional CLI options and wt-runner configuration.
- [Compile a Workflow](../how-to/compile-workflow.md) — advanced compilation
  options.
- [`spec.yaml` reference](../reference/spec-yaml.md) — full syntax for
  `partial`, `map`, `mapvalues`, `skipif`, and task groups.

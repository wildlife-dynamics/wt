# How-To Guides

These guides build on the [Getting Started](getting-started.md) guide.
Each one introduces a single spec.yaml feature using the same `custom-tasks`
package from that guide.

---

## Partial arguments

**Prerequisite:** Complete [Getting Started](getting-started.md) through
Step 4.

Use `partial` to bind one or more parameters at compile time so they are no
longer user-configurable. In the spec below, `b` is fixed to `5` — only `a`
remains as a runtime parameter:

```yaml
--8<-- "examples/getting-started/partial/spec.yaml"
```

### Compile and run

```bash
wt-compiler compile --spec spec.yaml --clobber
cd wt-add-with-partial-workflow
pixi run wt-add-with-partial-workflow run --config-json '{"total": {"a": 1}}'
```

!!! tip "`--clobber`"
    Overwrites the output directory if it already exists. Without it, the
    compiler refuses to overwrite a previous compilation.

### Expected result

```json
{"result": 6, "error": null, "trace": null}
```

### How it works

- `partial` fixes `b` to `5`. Only `a` remains as a user parameter.
- The result is `1 + 5 = 6`.
- Partial arguments can be literal values (integers, strings, lists) or
  `${{ }}` references to other task outputs.

### Auto-generated form

Because `b` is fixed via `partial`, the form only shows `a`:

<div class="rjsf-form" data-schema-url="../examples/getting-started/partial/rjsf.json"></div>

??? example "rjsf.json"

    ```json
    --8<-- "examples/getting-started/partial/rjsf.json"
    ```

---

## Chaining task outputs

**Prerequisite:** Complete [Getting Started](getting-started.md) through
Step 4.

Chain two tasks together so the output of one feeds into the next using
`${{ workflow.<id>.return }}` references:

```yaml
--8<-- "examples/getting-started/chaining-tasks/spec.yaml"
```

### Compile and run

```bash
wt-compiler compile --spec spec.yaml --clobber
cd wt-add-then-double-workflow
pixi run wt-add-then-double-workflow run --config-json '{"total": {"a": 3, "b": 3}}'
```

### Expected result

```json
{"result": 12, "error": null, "trace": null}
```

### How it works

- `${{ workflow.total.return }}` references the return value of the `total`
  task instance.
- Tasks must appear in **topological order** — every dependency before its
  dependent.
- The terminal task's return value becomes `result.json`'s `result` field.
- The result is `(3 + 3) × 2 = 12`.

### Auto-generated form

Because `doubled`'s only parameter (`n`) is bound via `${{ }}`, it has no
user-facing configuration. The generated web form only shows fields for
`total`:

<div class="rjsf-form" data-schema-url="../examples/getting-started/chaining-tasks/rjsf.json"></div>

??? example "rjsf.json"

    ```json
    --8<-- "examples/getting-started/chaining-tasks/rjsf.json"
    ```

For more on how the compiler generates form schemas, see
[Concepts — Auto-generated web forms](concepts.md#auto-generated-web-forms).

---

## Map fan-out

**Prerequisite:** Complete [Chaining task outputs](#chaining-task-outputs)
above.

A task can return any JSON-serializable type, including lists. When a task
returns a list, `map` lets you apply another task to every element — one
task instance per item.

The spec below chains three tasks: `add` produces a number, `split_digits`
breaks it into a list of digit strings, and `parse_int` is **mapped** over that
list to convert each string back to an integer:

```yaml
--8<-- "examples/tutorials/map/spec.yaml"
```

### Compile and run

```bash
wt-compiler compile --spec spec.yaml --clobber --install
cd wt-split-and-parse
pixi run workflow run
```

### Expected result

```json
{"result": [1, 2], "error": null, "trace": null}
```

### How it works

- `add` returns `12` (both arguments are bound via `partial`).
- `split_digits` returns `["1", "2"]`.
- `parse_int` is **mapped** over `["1", "2"]` — one task instance per element.
  `argnames: s` specifies which parameter of `parse_int` receives each element.
- The mapped result is `[1, 2]`.

??? info "Familiar with PySpark?"
    `map` is analogous to `RDD.map()` — it applies a function to each element
    of a sequence. The difference: PySpark maps over datasets with
    single-argument lambdas, while wt maps over a task's parameter. `argnames`
    specifies *which* parameter receives each element, since wt tasks can have
    multiple parameters.

`map` always produces a **list** whose length matches the input iterable.
Partial arguments (if any) are applied to every invocation.

!!! info "No web form for this workflow"
    Every parameter in this workflow is bound at compile time — `add` receives
    both `a` and `b` via `partial`, and the remaining tasks receive their inputs
    from `${{ }}` references or `map`. The compiled `rjsf.json` would contain an
    empty schema with no user-facing fields.

For the complete `map` and `mapvalues` reference, see
[spec.yaml — map](reference/spec-yaml.md#map).

---

## Coming soon

Additional guides (`mapvalues`, `skipif`, JSON schema customization,
environment variables, distributing workflows) are in progress.

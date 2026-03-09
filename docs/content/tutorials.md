# How-To Guides

These guides build on the [Getting Started](getting-started.md) guide.
Each one introduces a single spec.yaml feature using the same `custom-tasks`
package from that guide.

---

## Map fan-out

**Prerequisite:** Complete [Getting Started](getting-started.md) through
Step 5.

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

For the complete `map` and `mapvalues` reference, see
[spec.yaml — map](reference/spec-yaml.md#map).

---

## Coming soon

Additional guides (`mapvalues`, `skipif`, JSON schema customization,
environment variables, distributing workflows) are in progress.

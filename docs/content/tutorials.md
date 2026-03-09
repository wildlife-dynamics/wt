# How-To Guides

These guides build on the [Getting Started](getting-started.md) guide.
Each one introduces a single spec.yaml feature using the same `custom-tasks`
package from that guide.

---

## Map fan-out

**Prerequisite:** Complete [Getting Started](getting-started.md) through
Step 6 (Example 4).

In Example 4, `split_digits` returned `["1", "2"]` — a list of strings. What
if you want to convert each string back to an integer? That is what `map` does:
it applies a task to every element of a list.

The `custom-tasks` package includes a `parse_int` task that converts a string
to an integer. Here is a spec that splits a number into digits and then maps
`parse_int` over each one:

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
- `parse_int` is **mapped** over `["1", "2"]` — one invocation per element.
  `argnames: s` binds each element to the `s` parameter of `parse_int`.
- The mapped result is `[1, 2]`.

`map` always produces a **list** whose length matches the input iterable.
Partial arguments (if any) are applied to every invocation.

For the complete `map` and `mapvalues` reference, see
[spec.yaml — map](reference/spec-yaml.md#map).

---

## Coming soon

The following guides are planned:

- **`mapvalues`** — fan-out over key-value pairs, preserving keys
- **`skipif`** — conditional execution based on boolean functions
- **Customizing JSON schema** — controlling configuration form fields with type annotations and Pydantic models
- **Environment variables** — using `${{ env.VAR }}` in specs
- **Distributing workflows** — using Git and conda channel requirements for portable, shareable workflows

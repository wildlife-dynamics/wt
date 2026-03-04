# Write a spec.yaml

This guide covers practical patterns for authoring workflow specifications.
For the complete field-by-field reference, see the
[`spec.yaml` reference](../reference/spec-yaml.md).

---

## Starting from a blank spec

Every spec needs at minimum an `id`, `requirements`, and `workflow`:

```yaml
id: my_workflow

requirements:
  - name: my-tasks
    version: ">=0.1.0"

workflow:
  - id: step_one
    name: "First Step"
    task: my_function
```

- **`id`** must be a valid Python identifier (letters, digits, underscores).
- **`requirements`** lists the conda packages containing your registered tasks.
- **`workflow`** is an ordered list of task instances, executed top to bottom.

---

## Wiring data between tasks

Use `${{ workflow.<id>.return }}` to reference the return value of an earlier
task:

```yaml
workflow:
  - id: fetch
    name: "Fetch Data"
    task: fetch_records

  - id: process
    name: "Process Data"
    task: transform_records
    partial:
      records: ${{ workflow.fetch.return }}
```

Tasks must appear in **topological order** — every dependency must be listed
before the task that uses it.

---

## Common patterns

### Fan-out with `map`

Apply a task to each element of a sequence:

```yaml
  - id: results
    name: "Process Each Item"
    task: process_item
    map:
      argnames: item
      argvalues: ${{ workflow.fetch.return }}
```

`argnames` is the parameter name to bind each element to. `argvalues` is a
reference to the iterable. The result is a list with one entry per input item.

The upstream task that produces `argvalues` must return a `Sequence` (e.g.
`list`, `tuple`). You will typically define a registered function that returns
the iterable:

```python
@register()
def fetch_items(source: str) -> list[dict]:
    """Fetch items to process. Returns a list that map iterates over."""
    ...
```

### Fan-out with `mapvalues`

Like `map`, but operates on key-value pairs and preserves the keys:

```yaml
  - id: results
    name: "Process Each Group"
    task: process_group
    mapvalues:
      argnames: group_data
      argvalues: ${{ workflow.grouped.return }}
```

The upstream task must return a `Sequence[tuple[K, V]]` — a sequence of
two-element `(key, value)` tuples. The result is a `Sequence[tuple[K, R]]`
with the same keys, where each value is replaced by the task's return value.

You will need a registered function that produces data in this shape:

```python
@register()
def group_by_region(data: list[dict]) -> list[tuple[str, list[dict]]]:
    """Group records by region. Returns (key, value) pairs for mapvalues."""
    ...
```

### Binding static arguments with `partial`

Pass literal values or references as keyword arguments:

```yaml
  - id: filtered
    name: "Filter Records"
    task: filter_by_threshold
    partial:
      data: ${{ workflow.fetch.return }}
      threshold: 0.5
      include_nulls: false
```

You can mix literal values and `${{ }}` references in the same `partial` block.

### Conditional execution with `skipif`

Skip a task based on one or more condition functions:

```yaml
  - id: expensive_step
    name: "Run Model"
    task: run_model
    partial:
      data: ${{ workflow.fetch.return }}
    skipif:
      conditions:
        - is_dry_run
        - should_skip_model
      unpack_depth: 1
```

`skipif` has two fields:

- **`conditions`** — a list of registered function names (or fully qualified
  importable references). Each condition function receives the task's arguments
  and returns a `bool`. If any condition returns `True`, the task is skipped
  and returns `None`.
- **`unpack_depth`** — controls how deeply to unpack nested list-like arguments
  when evaluating conditions (default: `1`).

The condition functions must themselves be registered tasks with a signature
compatible with receiving the parent task's arguments.

### Task groups

Group related tasks under a heading for better organization in the generated
web form:

```yaml
  - type: task-group
    name: "Data Ingestion"
    tasks:
      - id: fetch_a
        name: "Fetch Source A"
        task: fetch_source_a
      - id: fetch_b
        name: "Fetch Source B"
        task: fetch_source_b
```

Groups are purely organizational — they do not affect execution order or
data flow.

---

## Compilation and validation

- Run `wt-compiler compile --spec spec.yaml` to compile your spec. Compilation
  includes full validation — the compiler checks task names, argument names,
  type compatibility, and topological ordering.
- Use `wt-registry --package my_tasks --format pretty` to see available
  task names and their parameter signatures before writing the spec.
- If two packages export a task with the same function name, use the fully
  qualified path: `my_tasks.tasks.process_item` instead of just
  `process_item`.

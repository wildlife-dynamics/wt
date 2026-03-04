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

Apply a task to each element of an iterable:

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

The input must be a dict-like structure. The result is a dict with the same
keys, where each value is the task's return value for that key.

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

Skip a task based on a boolean condition function:

```yaml
  - id: expensive_step
    name: "Run Model"
    task: run_model
    partial:
      data: ${{ workflow.fetch.return }}
    skipif:
      - id: check_skip
        task: is_dry_run
        partial:
          mode: ${{ workflow.config.return }}
```

The `skipif` block contains one or more condition checks. If any returns
`True`, the task is skipped and returns `None`.

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

## Validation tips

- Run `wt-compiler compile --spec spec.yaml` to validate your spec. The
  compiler checks task names, argument names, type compatibility, and
  topological ordering.
- Use `wt-registry --package my_tasks --format pretty` to see available
  task names and their parameter signatures before writing the spec.
- If two packages export a task with the same function name, use the fully
  qualified path: `my_tasks.tasks.process_item` instead of just
  `process_item`.

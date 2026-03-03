# Workflow Specification (`spec.yaml`)

A workflow specification defines the tasks, dependencies, and configuration
for a compiled workflow. This page is a complete reference for the `spec.yaml`
format consumed by `wt-compiler`.

---

## Root Structure

```yaml
id: my_workflow

requirements:
  - name: my-tasks-package
    version: ">=1.0"

rjsf-overrides: {}          # optional
task-instance-defaults: {}   # optional

workflow:
  - id: step_one
    task: do_something
    # ...
```

| Field | Type | Required | Description |
|-------|------|:--------:|-------------|
| `id` | string | yes | Unique workflow identifier. Must be a valid Python identifier (max 64 chars). Cannot collide with Python keywords, builtins, or any task ID in the workflow. |
| `requirements` | list | yes | Conda packages the workflow needs at runtime. See [Requirements](#requirements). |
| `rjsf-overrides` | object | no | Overrides for React JSON Schema Form rendering. See [RJSF Overrides](#rjsf-overrides). |
| `task-instance-defaults` | object | no | Defaults applied to every task instance. See [Task Instance Defaults](#task-instance-defaults). |
| `workflow` | list | yes | Ordered list of [task instances](#task-instances) and [task groups](#task-groups). Must be in topological order — every dependency appears before its dependent. |

### Validation rules

- All task IDs must be globally unique.
- No task ID may equal the spec `id`.
- Every `${{ workflow.<id>.return }}` reference must point to a task defined
  earlier in the list.
- Circular dependencies are forbidden.

---

## `requirements`

Each entry describes a conda package needed at runtime.

!!! note
    `requirements` currently resolves from **conda channels only**. PyPI
    support is on the roadmap. See
    [Tooling & Prerequisites](../concepts/tooling.md#how-requirements-resolves-today)
    for details on packaging options and the PyPI roadmap.

```yaml
requirements:
  - name: python
    version: ">=3.10,<4"
  - name: ecoscope-workflows-core
    version: ">=1.0"
    channel: "https://repo.prefix.dev/ecoscope-workflows"
  - requirement: "pandas>=2.0.0"      # shorthand
```

| Field | Type | Required | Default | Description |
|-------|------|:--------:|---------|-------------|
| `name` | string | yes* | — | Package name. |
| `version` | string | yes* | — | Version constraint (e.g. `">=3.10"`, `"==1.2.3"`, `"*"`). |
| `channel` | string | no | `"conda-forge"` | Conda channel. |
| `requirement` | string | yes* | — | Shorthand that combines name and version (e.g. `"pandas>=2.0.0"`). |

\* Provide either `name`/`version` or `requirement`, not both.

---

## `rjsf-overrides`

Customizes how workflow parameters are rendered in React JSON Schema Form
(RJSF) UIs. Uses dotted-key notation to target nested schema paths.

```yaml
rjsf-overrides:
  properties:
    get_events_data.properties.event_types:
      title: "Event Types"
      description: "Select one or more event types to include"
      items:
        type: string
        enum: ["immobility", "mortality", "geofence_break"]

  uiSchema:
    get_events_data.event_types:
      ui:widget: "select"
      ui:options:
        displayLabel: false

  $defs:
    ValueGrouper.oneOf:
      - const: "event_category"
        title: "Event Category"
      - const: "event_type"
        title: "Event Type"
```

| Section | Purpose |
|---------|---------|
| `properties` | Override JSON Schema properties (titles, descriptions, defaults, enums, constraints). |
| `uiSchema` | Override RJSF UI rendering (widgets, layout, help text). |
| `$defs` | Override shared JSON Schema definitions (e.g. constrain model `oneOf` choices). |

---

## `task-instance-defaults`

Defaults applied to every task instance in the workflow. Currently supports
only `skipif`. A task-level value overrides the default.

```yaml
task-instance-defaults:
  skipif:
    conditions:
      - is_dry_run

workflow:
  - id: step_one
    task: extract
    # inherits skipif from defaults

  - id: step_two
    task: transform
    skipif:
      conditions:
        - custom_condition
    # overrides defaults with its own skipif
```

---

## `workflow`

The `workflow` list contains the tasks that make up the workflow. Each entry
is either a [task instance](#task-instances) or a [task group](#task-groups).
Entries must be in topological order — every dependency must appear before
its dependent.

### Task Instances

A task instance is a single invocation of a registered task function.

```yaml
- id: get_data
  name: "Fetch Raw Data"
  task: ecoscope_workflows_core.tasks.get_events
  partial:
    time_range: ${{ workflow.time_range.return }}
    event_types: ["immobility", "mortality"]
```

| Field | Type | Required | Default | Description |
|-------|------|:--------:|---------|-------------|
| `id` | string | yes | — | Unique identifier, used as a variable name in the compiled DAG. Valid Python identifier, max 32 chars, cannot be a Python keyword or builtin. |
| `name` | string | no | `""` | Human-readable display name. |
| `task` | string | yes | — | Registered task reference — either a short name (if globally unique) or a fully qualified dotted path (e.g. `mypackage.tasks.extract`). |
| `partial` | object | no | `{}` | Static keyword arguments bound to the task. See [`partial`](#partial). |
| `map` | object | no | `{}` | Apply the task across an iterable. See [`map`](#map). |
| `mapvalues` | object | no | `{}` | Apply the task across key-value pairs. See [`mapvalues`](#mapvalues). |
| `skipif` | object | no | `null` | Conditional skip configuration. See [`skipif`](#skipif). |

!!! note
    A task instance uses exactly one execution method: **call** (the default),
    **map**, or **mapvalues**. If both `map` and `mapvalues` are present,
    validation fails.

#### `partial`

Binds keyword arguments to a task. Keys must match the task function's
parameter names.

```yaml
- id: create_chart
  task: create_bar_chart
  partial:
    title: "Event Summary"
    data: ${{ workflow.get_events.return }}
    color: "#4a90d9"
    api_key: ${{ env.CHART_API_KEY }}
```

When the compiled workflow runs, these arguments are passed to the task
function via its `.partial()` method — they are fixed for every invocation.

##### Variable references

Values in `partial` (and in `map`/`mapvalues` `argvalues`) can reference
task outputs or environment variables using the `${{ ... }}` syntax.

**Task output** — references the return value of a previously defined task:

```yaml
${{ workflow.<task_id>.return }}
```

The referenced task must appear earlier in the workflow (topological ordering).

**Environment variable** — resolved at runtime from `os.environ`:

```yaml
${{ env.<VAR_NAME> }}
```

**Inline values** — any YAML literal (numbers, strings, booleans, `null`,
lists, dicts) can be used directly:

```yaml
partial:
  count: 100
  label: "events"
  enabled: true
  options: null
  tags: ["a", "b", "c"]
```

**Mixing references and literals** — lists and dicts can freely combine
variable references with inline values:

```yaml
partial:
  sources:
    - ${{ workflow.source_a.return }}
    - ${{ workflow.source_b.return }}
    - "/static/fallback.csv"
  config:
    data: ${{ workflow.extract.return }}
    threshold: 0.95
    debug: false
```

#### `map`

Applies a task to each element of an iterable, producing a list of results.

```yaml
- id: process_regions
  task: process_region
  partial:
    template: "default"
  map:
    argnames: region
    argvalues: ${{ workflow.get_regions.return }}
```

| Field | Type | Required | Description |
|-------|------|:--------:|-------------|
| `argnames` | string or list | yes | Parameter name(s) to bind each element to. |
| `argvalues` | reference(s) | yes | Variable reference(s) to the iterable(s). |

Both fields must be provided together, or both omitted.

**Single argument:**

```yaml
map:
  argnames: item
  argvalues: ${{ workflow.get_items.return }}
```

Equivalent to: `[task(item=x) for x in get_items()]`

**Multiple arguments:**

```yaml
map:
  argnames: [year, month]
  argvalues: ${{ workflow.get_date_pairs.return }}
```

Equivalent to: `[task(year=y, month=m) for y, m in get_date_pairs()]`

#### `mapvalues`

Applies a task to the values of key-value pairs, preserving the keys in the
output.

```yaml
- id: transform_by_group
  task: transform
  mapvalues:
    argnames: dataset
    argvalues: ${{ workflow.grouped_data.return }}
```

| Field | Type | Required | Description |
|-------|------|:--------:|-------------|
| `argnames` | string or list | yes | Parameter name to bind each value to. |
| `argvalues` | reference(s) | yes | Variable reference(s) to key-value pair iterable(s). |

Input: `[("group_a", data_a), ("group_b", data_b)]`
Output: `[("group_a", result_a), ("group_b", result_b)]`

#### `skipif`

Conditionally skip a task based on one or more boolean condition functions.

```yaml
- id: expensive_step
  task: run_analysis
  skipif:
    conditions:
      - should_skip_analysis
    unpack_depth: 1
  partial:
    data: ${{ workflow.extract.return }}
```

| Field | Type | Required | Default | Description |
|-------|------|:--------:|---------|-------------|
| `conditions` | list | yes | — | Registered task names that return a boolean. If **any** returns `True`, the task is skipped and a `SkipSentinel` value is returned. |
| `unpack_depth` | int | no | `1` | Controls unpacking depth of nested list-like arguments when evaluating conditions. |

### Task Groups

A task group is a logical container for related task instances. Groups are
flattened during compilation — they affect documentation and UI presentation
but not execution order.

```yaml
- type: task-group
  title: "Data Extraction"
  description: "Fetch data from all configured sources"
  tasks:
    - id: fetch_events
      task: get_events
      partial:
        client: ${{ workflow.er_client.return }}
    - id: fetch_patrols
      task: get_patrols
      partial:
        client: ${{ workflow.er_client.return }}
```

| Field | Type | Required | Description |
|-------|------|:--------:|-------------|
| `type` | `"task-group"` | yes | Literal marker that identifies this entry as a group. |
| `title` | string | yes | Group title. |
| `description` | string | yes | Group description. |
| `tasks` | list | yes | List of [task instances](#task-instances). |

!!! note
    Task groups cannot be nested. Task IDs inside a group must still be
    globally unique across the entire workflow.

---

## Complete Example

```yaml
id: patrol_events_dashboard

requirements:
  - name: ecoscope-workflows-core
    version: ">=1.0"
    channel: "https://repo.prefix.dev/ecoscope-workflows"

rjsf-overrides:
  properties:
    get_events_data.properties.event_types:
      items:
        enum: ["immobility", "mortality"]
  uiSchema:
    er_client_name:
      ui:widget: "select"

task-instance-defaults:
  skipif:
    conditions:
      - is_dry_run

workflow:
  # -- setup --
  - id: workflow_details
    name: "Workflow Details"
    task: set_workflow_details
    partial:
      title: "Patrol Events Dashboard"

  - id: er_client
    name: "Data Source"
    task: set_er_connection

  - id: time_range
    name: "Time Range"
    task: set_time_range

  # -- data extraction --
  - type: task-group
    title: "Data Extraction"
    description: "Fetch patrol and event data from EarthRanger"
    tasks:
      - id: get_events
        name: "Get Events"
        task: get_events
        partial:
          client: ${{ workflow.er_client.return }}
          time_range: ${{ workflow.time_range.return }}
          event_types: ["immobility", "mortality"]

      - id: get_patrols
        name: "Get Patrols"
        task: get_patrols
        partial:
          client: ${{ workflow.er_client.return }}
          time_range: ${{ workflow.time_range.return }}

  # -- grouping --
  - id: groupers
    name: "Set Groupers"
    task: set_groupers

  # -- widgets --
  - id: event_count
    name: "Event Count Widget"
    task: create_single_value_widget_single_view
    partial:
      data: ${{ workflow.get_events.return }}
      label: "Total Events"

  - id: patrol_map
    name: "Patrol Map Widget"
    task: create_map_widget_single_view
    partial:
      data: ${{ workflow.get_patrols.return }}
      title: "Patrol Coverage"

  # -- dashboard assembly --
  - id: dashboard
    name: "Gather Dashboard"
    task: gather_dashboard
    partial:
      details: ${{ workflow.workflow_details.return }}
      time_range: ${{ workflow.time_range.return }}
      widgets:
        - ${{ workflow.event_count.return }}
        - ${{ workflow.patrol_map.return }}
      groupers: ${{ workflow.groupers.return }}
```

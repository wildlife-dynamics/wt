# Spec Models (Python API)

This page documents the Pydantic models that represent a parsed workflow specification. These are the Python-side counterparts to the [YAML spec format](../spec-yaml.md). The compiler validates raw YAML data against these models after task discovery populates the global `known_tasks` registry.

**Module:** `wt_compiler.spec`

---

## `Spec`

The root model for a complete workflow specification. Corresponds to the top-level structure of a `spec.yaml` file.

```python
class Spec(_ForbidExtra):
    id: SpecId
    requirements: list[SpecRequirement]
    rjsf_overrides: ReactJSONSchemaFormOverrides  # alias: "rjsf-overrides"
    task_instance_defaults: TaskInstanceDefaults   # alias: "task-instance-defaults"
    workflow: list[TaskInstance | TaskGroup]
```

### Fields

| Field | Type | YAML Key | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | `SpecId` | `id` | -- (required) | Unique identifier for the workflow. Must be a valid Python identifier, not a keyword/builtin, and at most 64 characters. |
| `requirements` | `list[SpecRequirement]` | `requirements` | -- (required) | Conda package requirements for the workflow |
| `rjsf_overrides` | `ReactJSONSchemaFormOverrides` | `rjsf-overrides` | `ReactJSONSchemaFormOverrides()` | Overrides for the generated React JSON Schema Form configuration |
| `task_instance_defaults` | `TaskInstanceDefaults` | `task-instance-defaults` | `TaskInstanceDefaults()` | Default options applied to any task instance that does not declare its own value |
| `workflow` | `list[TaskInstance \| TaskGroup]` | `workflow` | -- (required) | Ordered list of task instances and/or task groups defining the DAG |

### Computed Properties

| Property | Type | Description |
|----------|------|-------------|
| `flat_workflow` | `list[TaskInstance]` | All task instances flattened from groups, with defaults applied |
| `task_instance_dependencies` | `dict[str, list[str]]` | Mapping of each task ID to the task IDs it depends on |
| `all_task_ids` | `dict[str, str]` | Mapping of task ID to human-readable name |
| `sha256` | `str` | SHA256 hash of the spec (excluding requirements) |
| `requires_local_release_artifacts` | `bool` | Whether any requirement uses a local `file://` channel |

### Validators

The `Spec` model enforces these constraints at parse time:

- **No ID collision with spec ID** -- No task instance `id` may equal the spec `id`.
- **Unique task IDs** -- All task instance IDs must be unique across the workflow.
- **Valid dependency references** -- Every task ID referenced in `partial`, `map`, or `mapvalues` must be the `id` of another task in the workflow.
- **Topological ordering** -- Task instances must be listed in dependency order (a task's dependencies must appear before it).

---

## `TaskInstance`

A single task execution within the workflow.

```python
class TaskInstance(_ForbidExtra):
    name: str
    id: TaskInstanceId
    known_task_name: ImportableReference | KnownTaskName  # alias: "task"
    skipif: SkipIf | None
    partial: PartialKwargs
    map: MapOperation
    mapvalues: MapValuesOperation
```

### Fields

| Field | Type | YAML Key | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | `str` | `name` | `""` | Human-readable display name |
| `id` | `TaskInstanceId` | `id` | -- (required) | Unique identifier. Must be a valid Python identifier, not a keyword/builtin/known-task-name, at most 32 characters. |
| `known_task_name` | `str` | `task` | -- (required) | Registered task name or fully qualified importable reference |
| `skipif` | `SkipIf \| None` | `skipif` | `None` | Conditions under which to skip execution |
| `partial` | `PartialKwargs` | `partial` | `{}` | Static keyword arguments bound to every invocation |
| `map` | `MapOperation` | `map` | `MapOperation()` | Parallel map operation configuration |
| `mapvalues` | `MapValuesOperation` | `mapvalues` | `MapValuesOperation()` | Parallel mapvalues operation configuration |

### Computed Properties

| Property | Type | Description |
|----------|------|-------------|
| `known_task` | `KnownTask` | Resolved `KnownTask` from the global registry |
| `method` | `str` | Execution method: `"map"`, `"mapvalues"`, or `"call"` |
| `all_dependencies` | `list[Any]` | All dependency variables from partial, map, and mapvalues |
| `all_dependencies_dict` | `dict[str, list[str]]` | Dependencies as `{arg_name: [task_ids]}` |
| `flattened_partial_values` | `list[TaskIdVariable]` | All `TaskIdVariable` instances from partial values |

### Validators

- A task cannot depend on itself.
- `map` and `mapvalues` are mutually exclusive (only one may be set).
- The `known_task_name` must resolve to a registered task.

### Variable References in `partial`

Values in the `partial` dict can be:

- **Inline values** -- Literal strings, numbers, booleans, lists, or dicts.
- **Variable references** -- Strings of the form `${{ workflow.<task_id>.return }}` (reference another task's return value) or `${{ env.<ENV_VAR_NAME> }}` (reference an environment variable).
- **Mixed structures** -- Dicts and lists may contain a mix of inline values and variable references.

---

## `TaskGroup`

A named group of related tasks. Groups are purely organizational; the compiler flattens them for execution but preserves the hierarchy in the RJSF parameter form.

```python
class TaskGroup(_ForbidExtra):
    title: str
    description: str
    tasks: list[TaskInstance]
    type: Literal["task-group"] = "task-group"
```

| Field | Type | Description |
|-------|------|-------------|
| `title` | `str` | Human-readable title for the group |
| `description` | `str` | Description of the group's purpose |
| `tasks` | `list[TaskInstance]` | Task instances in this group |
| `type` | `Literal["task-group"]` | Discriminator field (always `"task-group"`) |

---

## `SpecRequirement`

A conda package requirement for the workflow.

```python
class SpecRequirement(_AllowArbitraryAndForbidExtra):
    name: str
    version: NamelessMatchSpecType
    channel: ChannelType
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | -- (required) | Package name |
| `version` | `NamelessMatchSpecType` | -- (required) | Version constraint (e.g., `>=1.0.0`) |
| `channel` | `ChannelType` | `conda-forge` | Conda channel |

Can be constructed from separate fields or from a single requirement string:

```python
# Separate fields
SpecRequirement(name="pandas", version=">=2.0", channel="conda-forge")

# Requirement string
SpecRequirement(requirement="pandas>=2.0.0")
```

---

## `KnownTask`

Metadata for a discovered/registered task function. Populated by the discovery module after running `wt-registry` in an ephemeral environment.

```python
class KnownTask(BaseModel):
    importable_reference: ImportableReference
    tags: list[TaskTag]
    registry_ref: int
    json_schema: dict[str, Any]
    description: str | None
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `importable_reference` | `ImportableReference` | -- (required) | Fully qualified dotted import path (e.g., `my_package.tasks.fetch_data`) |
| `tags` | `list[TaskTag]` | `[]` | Task tags (currently `TaskTag.io` is the only variant) |
| `registry_ref` | `int` | `0` | Disambiguation index for tasks with the same function name from different modules |
| `json_schema` | `dict[str, Any]` | `{}` | JSON schema for the task's parameters (from `wt-registry` CLI output) |
| `description` | `str \| None` | `None` | Human-readable description |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `anchor` | `str` | Module path portion of the importable reference |
| `function_name` | `str` | Function name portion of the importable reference |
| `safe_reference` | `str` | Code-generation-safe name (appends `_N` suffix if `registry_ref > 0`) |

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `parameters_jsonschema(omit_args=None)` | `dict[str, Any]` | JSON schema with specified arguments removed |

---

## `TaskInstanceDefaults`

Default options applied to task instances that do not declare their own.

```python
class TaskInstanceDefaults(_ForbidExtra):
    skipif: SkipIf | None = None
```

Currently the only default is `skipif`. If a task instance does not declare its own `skipif`, the spec-level default is applied.

---

## Supporting Models

### `MapOperation`

Configuration for a `.map()` parallel operation.

```python
class MapOperation(_ForbidExtra):
    argnames: ParallelOpArgNames    # list[str]
    argvalues: Vars                 # list of variable references
```

Both `argnames` and `argvalues` must be provided together or both left empty. An empty `MapOperation` evaluates to `False` in boolean context.

### `MapValuesOperation`

Configuration for a `.mapvalues()` parallel operation. Same structure as `MapOperation`.

### `SkipIf`

Conditional skip configuration for a task instance.

```python
class SkipIf(_ForbidExtra):
    conditions: list[ImportableReference | KnownTaskName]
    unpack_depth: int = 1
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `conditions` | `list[str]` | `[]` | Task names or importable references used as condition functions |
| `unpack_depth` | `int` | `1` | Depth of nested list/tuple unpacking before evaluating conditions |

### `TaskTag`

```python
class TaskTag(str, Enum):
    io = "io"
```

Currently the only tag. Tasks tagged `io` receive mock imports in test DAGs.

### Variable Types

| Type | Description |
|------|-------------|
| `TaskIdVariable` | References `${{ workflow.<task_id>.return }}` -- another task's return value |
| `EnvVariable` | References `${{ env.<NAME> }}` -- an environment variable |
| `InlineValue` | A literal JSON-serializable value |
| `VariableValuesDict` | A dict whose values may be variable references or inline values |
| `VariableValuesList` | A list whose elements may be variable references, inline values, or nested structures |

---

## Global State: `known_tasks`

```python
known_tasks: dict[str, dict[str, KnownTask]] = {}
```

A module-level dictionary mapping `function_name -> {module_path -> KnownTask}`. This dict is populated by `discovery.populate_known_tasks()` before `Spec` validation, since many validators reference it to check that task names are valid.

!!! warning
    `known_tasks` is global mutable state. It must be populated before constructing a `Spec` instance. The `compile_workflow_from_yaml()` function handles this automatically.

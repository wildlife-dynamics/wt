# wt-contracts

`wt-contracts` is the **foundation package** of the wt monorepo. It provides
Pydantic models and Python Protocols that define the type-safe interfaces used
for inter-package communication. Every other wt package depends on
`wt-contracts`.

**Modules:** `registry` · `task` · `cli`

**Public API** (re-exported from `wt_contracts`):

```python
from wt_contracts import (
    RegistryMetadata,
    RegistryEntry,
    RegistryOutput,
    TaskProtocol,
    WorkflowCLIArgs,
    WorkflowCLIEnv,
)
```

---

## Registry Models

These models define the JSON schema for `wt-registry` CLI output — the
serialization boundary between wt-registry and wt-compiler.

### `RegistryMetadata`

Metadata for a registered function.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `title` | `str` | *(required)* | Human-readable title |
| `description` | `str \| None` | `None` | Extended description |
| `tags` | `list[str]` | `[]` | Categorization tags |
| `deprecated` | `bool` | `False` | Whether the function is deprecated |
| `deprecation_message` | `str \| None` | `None` | Explanation of what to use instead |

### `RegistryEntry`

A complete registry entry representing a single discovered function.

| Field | Type | Description |
|-------|------|-------------|
| `metadata` | `RegistryMetadata` | Function metadata |
| `module_path` | `str` | Fully qualified module path (e.g. `my_tasks.tasks`) |
| `public_module_path` | `str` | Shortest importable path (e.g. `my_tasks`) |
| `function_name` | `str` | Function name (e.g. `calculate_mean`) |
| `import_statement` | `str` | Ready-to-use import statement |
| `json_schema` | `dict` | JSON Schema derived from function type annotations |

### `RegistryOutput`

Top-level schema for the JSON output of the `wt-registry` CLI.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `entries` | `dict[str, RegistryEntry]` | *(required)* | Mapping from fully qualified name to entry |
| `version` | `str` | `"1.0.0"` | Schema version |

---

## Task Protocol

### `TaskProtocol[P, R]`

A generic `typing.Protocol` parameterized by `P` (`ParamSpec`) and `R`
(`TypeVar`) that specifies the methods task wrappers must implement. The
compiler generates code that calls these methods; `wt-task` provides the
concrete implementation (`SyncTask`, `AsyncTask`).

| Method | Signature | Description |
|--------|-----------|-------------|
| `partial` | `(**kwargs) -> Self` | Apply partial function application |
| `call` | `(*args, **kwargs) -> R` | Execute the task |
| `map` | `(argname, argvalues, **kwargs) -> Sequence[R]` | Map over a sequence |
| `mapvalues` | `(argname, argvalues, **kwargs) -> Sequence[tuple[Any, R]]` | Map over key-value pairs preserving keys |
| `validate` | `() -> Self` | Enable Pydantic validation |
| `skipif` | `(condition) -> Self` | Conditionally skip execution |
| `set_executor` | `(executor) -> Self` | Set a custom executor |

---

## CLI Models

These models define the standard arguments and environment variables that
generated workflow scripts accept and that invokers construct.

### `WorkflowCLIArgs`

Standard CLI arguments accepted by generated workflow scripts.

| Field | Type | Description |
|-------|------|-------------|
| `params` | `str \| None` | JSON string of workflow parameters |
| `params_file` | `str \| None` | Path to YAML/JSON parameters file |
| `output_dir` | `str \| None` | Directory for output files |
| `trace_file` | `str \| None` | Path for trace output |
| `log_level` | `str \| None` | Logging level |

### `WorkflowCLIEnv`

Environment variables set by invokers when launching workflow processes.

| Field | Type | Description |
|-------|------|-------------|
| `WORKFLOW_RUN_ID` | `str \| None` | Unique run identifier |
| `WORKFLOW_TRACE_ENABLED` | `str \| None` | Whether tracing is enabled |
| `WORKFLOW_OUTPUT_DIR` | `str \| None` | Output directory path |

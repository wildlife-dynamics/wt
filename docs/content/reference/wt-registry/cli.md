# CLI Reference

Entry point: `wt-registry` (installed as a console script via `project.scripts`).

Module: `wt_registry.cli`

```bash
wt-registry [OPTIONS]
```

The `wt-registry` CLI exports the global function registry to stdout. It is primarily consumed by `wt-compiler` for task discovery via subprocess.

---

## Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--format {json,pretty}` | choice | `json` | Output format. `json` produces machine-readable JSON in the `RegistryOutput` schema. `pretty` produces human-readable text. |
| `--pretty` | flag | off | Pretty-print JSON output with indentation (only applies when `--format json`). |
| `--function NAME` | repeatable | all | Filter output to specific function names. Can be specified multiple times. Matches against the function name (not the fully-qualified name). |
| `--package PACKAGE` | repeatable | none | Python package to import before exporting the registry. Importing the package triggers `@register` decorators. Can be specified multiple times. Uses dotted module paths (e.g., `mypackage.tasks`). |

---

## Usage

### Basic Export

Import a package to trigger registration, then export all entries as JSON:

```bash
wt-registry --package mypackage.tasks
```

Output (compact JSON):

```json
{"entries":{"mypackage.tasks.process_data":{"metadata":{...},...}},"version":"1.0.0"}
```

### Pretty-Printed JSON

```bash
wt-registry --package mypackage.tasks --format json --pretty
```

Output:

```json
{
  "entries": {
    "mypackage.tasks.process_data": {
      "metadata": {
        "title": "Process Data",
        "description": "Process input data",
        "tags": ["etl"],
        "deprecated": false,
        "deprecation_message": null
      },
      "module_path": "mypackage.tasks._processing",
      "public_module_path": "mypackage.tasks",
      "function_name": "process_data",
      "import_statement": "from mypackage.tasks import process_data as process_data",
      "json_schema": { ... }
    }
  },
  "version": "1.0.0"
}
```

### Human-Readable Format

```bash
wt-registry --package mypackage.tasks --format pretty
```

Output:

```
=== mypackage.tasks.process_data ===
Title: Process Data
Description: Process input data
Tags: etl
Deprecated: No
Import: from mypackage.tasks._processing import process_data
```

### Filter by Function Name

Export only specific functions:

```bash
wt-registry --package mypackage.tasks --function process_data --function calculate_stats
```

### Multiple Packages

Import multiple packages:

```bash
wt-registry --package mypackage.tasks --package mypackage.io --format json --pretty
```

---

## How It Works

1. **Import packages.** Each `--package` argument is imported via `importlib.import_module()`. Importing the package executes the module-level `@register` decorators, which populate the global registry.

2. **Filter entries.** If `--function` flags are provided, the registry is filtered to include only entries whose `function_name` matches one of the specified names.

3. **Discover public paths.** When `--package` is provided, the CLI traverses the imported package modules to discover **public re-export paths**. If a function defined in `mypackage.tasks._internal` is re-exported in `mypackage.tasks.__init__`, the CLI uses `mypackage.tasks` as the `public_module_path` and builds the import statement accordingly.

4. **Serialize.** In `json` format, entries are converted to `wt_contracts.RegistryOutput` and serialized via `model_dump_json()`. In `pretty` format, entries are formatted as human-readable text.

5. **Output to stdout.** The result is printed to stdout. Errors and warnings (e.g., failed package imports) go to stderr.

---

## Public Path Discovery

When the `--package` flag is used, the CLI performs **public path discovery** to produce clean import statements. This traverses the package's module tree looking for re-exported functions:

```
mypackage/
    tasks/
        __init__.py          # from mypackage.tasks._processing import process_data
        _processing.py       # @register() def process_data(...): ...
```

Without `--package`, the import statement would reference the private module:

```python
from mypackage.tasks._processing import process_data as process_data
```

With `--package mypackage.tasks`, the CLI discovers the re-export and produces:

```python
from mypackage.tasks import process_data as process_data
```

The discovery algorithm prefers the **shortest** public path when a function is re-exported at multiple levels.

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error during export (e.g., validation failure, schema generation error) |

Import warnings (packages that cannot be imported) are printed to stderr but do not cause a non-zero exit code.

---

## Integration with wt-compiler

`wt-compiler` calls the `wt-registry` CLI as a subprocess to discover available tasks:

```bash
wt-registry --package mypackage.tasks --format json
```

It then parses the JSON output as a `RegistryOutput` model and uses the entries to generate the workflow DAG code.

# CLI Models

Module: `wt_contracts.cli`

These Pydantic models define the standard CLI interface for generated workflows. `wt-compiler` generates workflow scripts that accept these arguments, and `wt-invokers` constructs them when launching workflow subprocesses.

---

## WorkflowCLIArgs

```python
from wt_contracts import WorkflowCLIArgs
```

Standard CLI arguments accepted by generated workflow scripts.

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `params` | `str` | `"{}"` | JSON string or file path containing workflow parameters. |
| `params_file` | `str \| None` | `None` | Path to a parameters file (alternative to `params`). |
| `output_dir` | `str \| None` | `None` | Directory for workflow outputs. |
| `trace_file` | `str \| None` | `None` | File path for the execution trace. |
| `log_level` | `str` | `"INFO"` | Logging level (e.g., `"DEBUG"`, `"INFO"`, `"WARNING"`). |

### Example

```python
from wt_contracts import WorkflowCLIArgs

# Inline parameters
args = WorkflowCLIArgs(
    params='{"input": "data.csv", "threshold": 0.5}',
    output_dir="/tmp/workflow-output",
    trace_file="/tmp/trace.json",
    log_level="DEBUG",
)

# Parameters from file
args = WorkflowCLIArgs(
    params_file="/path/to/params.json",
    output_dir="/tmp/workflow-output",
)
```

!!! note "`params` vs. `params_file`"
    These two fields provide alternative ways to supply workflow parameters. `params` accepts an inline JSON string, while `params_file` points to a JSON file on disk. When both are provided, the behavior is determined by the generated workflow script.

---

## WorkflowCLIEnv

```python
from wt_contracts import WorkflowCLIEnv
```

Standard environment variables set by invokers when launching workflow subprocesses.

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `WORKFLOW_RUN_ID` | `str \| None` | `None` | Unique identifier for the workflow run. |
| `WORKFLOW_TRACE_ENABLED` | `str` | `"false"` | Whether tracing is enabled. Accepts `"true"` or `"false"`. |
| `WORKFLOW_OUTPUT_DIR` | `str \| None` | `None` | Directory for workflow outputs. |

### Example

```python
from wt_contracts import WorkflowCLIEnv

env = WorkflowCLIEnv(
    WORKFLOW_RUN_ID="run-12345",
    WORKFLOW_TRACE_ENABLED="true",
    WORKFLOW_OUTPUT_DIR="/tmp/output",
)

# Convert to a dict suitable for subprocess.Popen(env=...)
env_dict = env.model_dump(exclude_none=True)
# {"WORKFLOW_RUN_ID": "run-12345", "WORKFLOW_TRACE_ENABLED": "true", "WORKFLOW_OUTPUT_DIR": "/tmp/output"}
```

### Usage by Invokers

Invokers (e.g., the local subprocess invoker or the Cloud Batch invoker) set these environment variables before launching a workflow process:

```python
import subprocess
from wt_contracts import WorkflowCLIArgs, WorkflowCLIEnv

args = WorkflowCLIArgs(
    params='{"input": "data.csv"}',
    output_dir="/tmp/output",
)
env = WorkflowCLIEnv(
    WORKFLOW_RUN_ID="run-abc123",
    WORKFLOW_TRACE_ENABLED="true",
    WORKFLOW_OUTPUT_DIR="/tmp/output",
)

subprocess.run(
    ["python", "workflow.py", "--params", args.params],
    env={**env.model_dump(exclude_none=True)},
)
```

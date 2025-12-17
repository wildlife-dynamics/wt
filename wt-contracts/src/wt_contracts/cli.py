"""CLI contracts for generated workflows.

This module defines the standard CLI interface that wt-compiler generates
and wt-invokers calls. This ensures consistent CLI contracts across all
generated workflows.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WorkflowCLIArgs(BaseModel):
    """Standard CLI arguments for generated workflows.

    Generated workflow CLI scripts accept these arguments. wt-invokers
    constructs these arguments when calling workflows.

    Attributes:
        params: JSON string or file path containing workflow parameters
        params_file: Optional path to parameters file (alternative to params)
        output_dir: Optional directory for workflow outputs
        trace_file: Optional file path for execution trace
        log_level: Logging level (default: "INFO")

    Examples:
        Constructing CLI arguments for invoker:

        >>> args = WorkflowCLIArgs(
        ...     params='{"input": "data.csv", "threshold": 0.5}',
        ...     output_dir="/tmp/workflow-output",
        ...     trace_file="/tmp/trace.json",
        ...     log_level="DEBUG"
        ... )
        >>> args.params
        '{"input": "data.csv", "threshold": 0.5}'

        Alternative with params file:

        >>> args = WorkflowCLIArgs(
        ...     params_file="/path/to/params.json",
        ...     output_dir="/tmp/workflow-output"
        ... )
        >>> args.params_file
        '/path/to/params.json'
    """

    params: str = Field(
        default="{}",
        description="JSON string or file path containing workflow parameters",
    )
    params_file: str | None = Field(
        default=None,
        description="Optional path to parameters file (alternative to params)",
    )
    output_dir: str | None = Field(
        default=None, description="Optional directory for workflow outputs"
    )
    trace_file: str | None = Field(
        default=None, description="Optional file path for execution trace"
    )
    log_level: str = Field(default="INFO", description="Logging level")


class WorkflowCLIEnv(BaseModel):
    """Standard environment variables for workflows.

    Generated workflows and invokers use these environment variables for
    configuration. This ensures consistent environment-based configuration.

    Attributes:
        WORKFLOW_RUN_ID: Unique identifier for workflow run
        WORKFLOW_TRACE_ENABLED: Whether tracing is enabled ("true"/"false")
        WORKFLOW_OUTPUT_DIR: Directory for workflow outputs

    Examples:
        Setting up environment for subprocess:

        >>> env = WorkflowCLIEnv(
        ...     WORKFLOW_RUN_ID="run-12345",
        ...     WORKFLOW_TRACE_ENABLED="true",
        ...     WORKFLOW_OUTPUT_DIR="/tmp/output"
        ... )
        >>> env.WORKFLOW_RUN_ID
        'run-12345'

        Converting to environment dict:

        >>> env = WorkflowCLIEnv(WORKFLOW_RUN_ID="run-12345")
        >>> env_dict = env.model_dump(exclude_none=True)
        >>> env_dict["WORKFLOW_RUN_ID"]
        'run-12345'
    """

    WORKFLOW_RUN_ID: str | None = Field(
        default=None, description="Unique identifier for workflow run"
    )
    WORKFLOW_TRACE_ENABLED: str = Field(
        default="false", description='Whether tracing is enabled ("true"/"false")'
    )
    WORKFLOW_OUTPUT_DIR: str | None = Field(
        default=None, description="Directory for workflow outputs"
    )

"""Tests for CLI contracts."""

import json

from wt_contracts.cli import WorkflowCLIArgs, WorkflowCLIEnv


class TestWorkflowCLIArgs:
    """Tests for WorkflowCLIArgs model."""

    def test_default_args(self) -> None:
        """Test creating CLI args with defaults."""
        args = WorkflowCLIArgs()

        assert args.params == "{}"
        assert args.params_file is None
        assert args.output_dir is None
        assert args.trace_file is None
        assert args.log_level == "INFO"

    def test_args_with_json_params(self) -> None:
        """Test CLI args with JSON string params."""
        params_json = '{"input": "data.csv", "threshold": 0.5}'
        args = WorkflowCLIArgs(params=params_json)

        assert args.params == params_json
        assert args.params_file is None

        # Verify it's valid JSON
        params = json.loads(args.params)
        assert params["input"] == "data.csv"
        assert params["threshold"] == 0.5

    def test_args_with_params_file(self) -> None:
        """Test CLI args with params file path."""
        args = WorkflowCLIArgs(params_file="/path/to/params.json")

        assert args.params_file == "/path/to/params.json"

    def test_args_with_output_dir(self) -> None:
        """Test CLI args with output directory."""
        args = WorkflowCLIArgs(params='{"key": "value"}', output_dir="/tmp/workflow-output")

        assert args.output_dir == "/tmp/workflow-output"

    def test_args_with_trace_file(self) -> None:
        """Test CLI args with trace file."""
        args = WorkflowCLIArgs(params='{"key": "value"}', trace_file="/tmp/trace.json")

        assert args.trace_file == "/tmp/trace.json"

    def test_args_with_custom_log_level(self) -> None:
        """Test CLI args with custom log level."""
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            args = WorkflowCLIArgs(params="{}", log_level=level)
            assert args.log_level == level

    def test_args_full_configuration(self) -> None:
        """Test CLI args with all fields set."""
        args = WorkflowCLIArgs(
            params='{"input": "data.csv"}',
            params_file="/backup/params.json",
            output_dir="/tmp/output",
            trace_file="/tmp/trace.json",
            log_level="DEBUG",
        )

        assert args.params == '{"input": "data.csv"}'
        assert args.params_file == "/backup/params.json"
        assert args.output_dir == "/tmp/output"
        assert args.trace_file == "/tmp/trace.json"
        assert args.log_level == "DEBUG"

    def test_args_serialization(self) -> None:
        """Test serializing CLI args to dict."""
        args = WorkflowCLIArgs(
            params='{"key": "value"}',
            output_dir="/tmp/output",
            log_level="DEBUG",
        )

        data = args.model_dump()

        assert data["params"] == '{"key": "value"}'
        assert data["output_dir"] == "/tmp/output"
        assert data["log_level"] == "DEBUG"
        assert data["params_file"] is None
        assert data["trace_file"] is None

    def test_args_serialization_exclude_none(self) -> None:
        """Test serializing with None values excluded."""
        args = WorkflowCLIArgs(params='{"key": "value"}', log_level="INFO")

        data = args.model_dump(exclude_none=True)

        assert "params" in data
        assert "log_level" in data
        assert "params_file" not in data
        assert "output_dir" not in data
        assert "trace_file" not in data

    def test_args_json_roundtrip(self) -> None:
        """Test JSON serialization roundtrip."""
        args = WorkflowCLIArgs(
            params='{"x": 1, "y": 2}',
            output_dir="/tmp/out",
            trace_file="/tmp/trace.json",
            log_level="DEBUG",
        )

        # Serialize to JSON
        json_str = args.model_dump_json()

        # Deserialize back
        args2 = WorkflowCLIArgs.model_validate_json(json_str)

        assert args2.params == args.params
        assert args2.output_dir == args.output_dir
        assert args2.trace_file == args.trace_file
        assert args2.log_level == args.log_level


class TestWorkflowCLIEnv:
    """Tests for WorkflowCLIEnv model."""

    def test_default_env(self) -> None:
        """Test creating env with defaults."""
        env = WorkflowCLIEnv()

        assert env.WORKFLOW_RUN_ID is None
        assert env.WORKFLOW_TRACE_ENABLED == "false"
        assert env.WORKFLOW_OUTPUT_DIR is None

    def test_env_with_run_id(self) -> None:
        """Test env with run ID."""
        env = WorkflowCLIEnv(WORKFLOW_RUN_ID="run-12345")

        assert env.WORKFLOW_RUN_ID == "run-12345"

    def test_env_with_tracing_enabled(self) -> None:
        """Test env with tracing enabled."""
        env = WorkflowCLIEnv(WORKFLOW_TRACE_ENABLED="true")

        assert env.WORKFLOW_TRACE_ENABLED == "true"

    def test_env_with_output_dir(self) -> None:
        """Test env with output directory."""
        env = WorkflowCLIEnv(WORKFLOW_OUTPUT_DIR="/tmp/workflow-output")

        assert env.WORKFLOW_OUTPUT_DIR == "/tmp/workflow-output"

    def test_env_full_configuration(self) -> None:
        """Test env with all fields set."""
        env = WorkflowCLIEnv(
            WORKFLOW_RUN_ID="run-abc123",
            WORKFLOW_TRACE_ENABLED="true",
            WORKFLOW_OUTPUT_DIR="/var/workflow/output",
        )

        assert env.WORKFLOW_RUN_ID == "run-abc123"
        assert env.WORKFLOW_TRACE_ENABLED == "true"
        assert env.WORKFLOW_OUTPUT_DIR == "/var/workflow/output"

    def test_env_to_dict(self) -> None:
        """Test converting env to dict for subprocess."""
        env = WorkflowCLIEnv(
            WORKFLOW_RUN_ID="run-xyz",
            WORKFLOW_TRACE_ENABLED="true",
            WORKFLOW_OUTPUT_DIR="/tmp/out",
        )

        env_dict = env.model_dump()

        assert env_dict["WORKFLOW_RUN_ID"] == "run-xyz"
        assert env_dict["WORKFLOW_TRACE_ENABLED"] == "true"
        assert env_dict["WORKFLOW_OUTPUT_DIR"] == "/tmp/out"

    def test_env_to_dict_exclude_none(self) -> None:
        """Test converting env to dict excluding None values."""
        env = WorkflowCLIEnv(WORKFLOW_RUN_ID="run-123")

        env_dict = env.model_dump(exclude_none=True)

        assert "WORKFLOW_RUN_ID" in env_dict
        assert "WORKFLOW_TRACE_ENABLED" in env_dict  # Has default value
        assert "WORKFLOW_OUTPUT_DIR" not in env_dict  # None excluded

    def test_env_json_roundtrip(self) -> None:
        """Test JSON serialization roundtrip."""
        env = WorkflowCLIEnv(
            WORKFLOW_RUN_ID="run-test-123",
            WORKFLOW_TRACE_ENABLED="true",
            WORKFLOW_OUTPUT_DIR="/path/to/output",
        )

        # Serialize to JSON
        json_str = env.model_dump_json()

        # Deserialize back
        env2 = WorkflowCLIEnv.model_validate_json(json_str)

        assert env2.WORKFLOW_RUN_ID == env.WORKFLOW_RUN_ID
        assert env2.WORKFLOW_TRACE_ENABLED == env.WORKFLOW_TRACE_ENABLED
        assert env2.WORKFLOW_OUTPUT_DIR == env.WORKFLOW_OUTPUT_DIR

    def test_env_boolean_as_string(self) -> None:
        """Test that WORKFLOW_TRACE_ENABLED is string, not bool."""
        env = WorkflowCLIEnv(WORKFLOW_TRACE_ENABLED="true")

        # Should be string "true", not boolean True
        assert env.WORKFLOW_TRACE_ENABLED == "true"
        assert isinstance(env.WORKFLOW_TRACE_ENABLED, str)

        env2 = WorkflowCLIEnv(WORKFLOW_TRACE_ENABLED="false")
        assert env2.WORKFLOW_TRACE_ENABLED == "false"
        assert isinstance(env2.WORKFLOW_TRACE_ENABLED, str)

    def test_env_merging_with_os_environ(self) -> None:
        """Test pattern for merging env with os.environ."""
        import os

        env = WorkflowCLIEnv(WORKFLOW_RUN_ID="run-merge-test", WORKFLOW_TRACE_ENABLED="true")

        # Pattern for subprocess.run(env=...)
        subprocess_env = {
            **os.environ,
            **env.model_dump(exclude_none=True),
        }

        assert "WORKFLOW_RUN_ID" in subprocess_env
        assert subprocess_env["WORKFLOW_RUN_ID"] == "run-merge-test"
        assert subprocess_env["WORKFLOW_TRACE_ENABLED"] == "true"


class TestCLIIntegration:
    """Integration tests for CLI contracts."""

    def test_args_and_env_together(self) -> None:
        """Test using args and env together (common pattern)."""
        # CLI arguments
        args = WorkflowCLIArgs(
            params='{"input": "data.csv"}',
            output_dir="/tmp/output",
            log_level="DEBUG",
        )

        # Environment variables
        env = WorkflowCLIEnv(WORKFLOW_RUN_ID="integration-test-123", WORKFLOW_TRACE_ENABLED="true")

        # Both should be independently configurable
        assert args.params == '{"input": "data.csv"}'
        assert env.WORKFLOW_RUN_ID == "integration-test-123"

    def test_subprocess_pattern(self) -> None:
        """Test typical subprocess invocation pattern."""
        args = WorkflowCLIArgs(
            params='{"key": "value"}',
            output_dir="/tmp/out",
            trace_file="/tmp/trace.json",
            log_level="INFO",
        )

        env = WorkflowCLIEnv(WORKFLOW_RUN_ID="subprocess-test", WORKFLOW_TRACE_ENABLED="true")

        # Build command line arguments (typical pattern)
        cmd_args = [
            "workflow-cli",
            "--params",
            args.params,
            "--output-dir",
            args.output_dir or "",
            "--trace-file",
            args.trace_file or "",
            "--log-level",
            args.log_level,
        ]

        # Build environment
        import os

        env_dict = {**os.environ, **env.model_dump(exclude_none=True)}

        # Verify structure
        assert "--params" in cmd_args
        assert "WORKFLOW_RUN_ID" in env_dict

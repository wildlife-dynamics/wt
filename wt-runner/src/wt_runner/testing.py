"""Testing utilities for workflow test cases.

Provides Case (Pydantic model) and CaseRunner (dataclass) for running
workflow test cases via either the FastAPI application or CLI.
"""

import asyncio
import traceback
import uuid
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Literal

import ruamel.yaml
from fastapi.testclient import TestClient
from pydantic import BaseModel
from rattler import MatchSpec
from wt_invokers.local import LocalSubprocessInvoker

from .app import get_results_json
from .tracing import OTelConsoleExporterDst, OtelExporterChoice


class Case(BaseModel):
    """A test case for a workflow.

    Args:
        name: Human-readable name of the test case.
        description: Description of what the test case covers.
        params: Workflow parameters to pass.
        raises: Whether the test case is expected to raise an error.
        expected_status_code: Expected HTTP status code (default 200).
    """

    name: str
    description: str
    params: dict[str, Any]
    raises: bool = False
    expected_status_code: int = 200


ExecutionMode = Literal["async", "sequential"]  # TODO: move to executors module


@dataclass
class CaseRunner:
    """Run a single test case for a workflow via either the FastAPI application or CLI.

    Args:
        execution_mode: The execution mode to test. One of "async" or "sequential".
        mock_io: Whether or not to mock IO with 3rd party services.
        case: The test case to run. Test cases are defined by the `test-cases.yaml` file.
        results_subdir: The temporary directory to use for the test.
        traceparent: The traceparent header to propagate tracing context. Optional.
        otel_exporter: The OpenTelemetry exporter to use. Optional. One of "console", or "gcp".
        otel_console_exporter_dst: The destination for the console exporter.
            One of "stdout" or "file".
    """

    execution_mode: ExecutionMode
    mock_io: bool
    case: Case
    results_subdir: Path
    traceparent: str | None = None
    otel_exporter: OtelExporterChoice | None = "console"
    otel_console_exporter_dst: OTelConsoleExporterDst = "file"

    def run_app(
        self,
        app: Any,  # noqa: ANN401  # accepts any FastAPI-compatible ASGI app
        data_connections_env_vars: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a single test case for a workflow via the FastAPI application.

        Args:
            app: The fastapi.App instance.
            data_connections_env_vars: Optional environment variables for data connections.

        Returns:
            Response JSON as a dictionary.
        """
        json_ = {
            "params": self.case.params,
            "data_connections_env_vars": data_connections_env_vars or {},
        }
        query_params = {
            "execution_mode": self.execution_mode,
            "mock_io": self.mock_io,
            "results_url": self.results_subdir.absolute().as_posix(),
        }
        headers = {"Content-Type": "application/json"}
        if self.traceparent:
            headers["traceparent"] = self.traceparent
        with TestClient(app) as client:
            response = client.post("/", json=json_, params=query_params, headers=headers)
            assert response.status_code == self.case.expected_status_code, (  # noqa: S101  # test helper assertion is the failure signal
                f"Test failed with {response.status_code = }, "
                f"which differs from {self.case.expected_status_code = }; "
                f"{response.text =}"
            )
        result: dict[str, Any] = response.json()
        return result

    def run_cli(self, matchspec: MatchSpec) -> dict[str, Any]:
        """Run a single test case for a workflow via the CLI.

        Args:
            matchspec: The matchspec of the workflow to run.

        Returns:
            Results dictionary.
        """
        invoker = LocalSubprocessInvoker(matchspec=matchspec, cwd=str(Path.cwd()))
        yaml = ruamel.yaml.YAML(typ="safe")
        config_text_stream = StringIO()
        yaml.dump(self.case.params, config_text_stream)

        async def _run() -> dict[str, Any]:
            try:
                await invoker.run(
                    workflow_run_id=uuid.uuid4().hex,
                    config_text=config_text_stream.getvalue(),
                    results_url=self.results_subdir.as_uri(),
                    execution_mode=self.execution_mode,
                    mock_io=self.mock_io,
                    extra_env=({"TRACEPARENT": self.traceparent} if self.traceparent else None),
                    otel_exporter=self.otel_exporter,
                    otel_console_exporter_dst=self.otel_console_exporter_dst,
                )
                await invoker.wait(timeout=300)
                result = await get_results_json(self.results_subdir.as_uri())
            except Exception as e:  # noqa: BLE001  # surface any error in the test result for diagnosis
                trace = traceback.format_exc()
                result = {"error": str(e), "trace": trace}

            if not isinstance(result, dict):
                raise RuntimeError(f"Unexpected {result = }. Expected dict.")
            return result

        return asyncio.run(_run())

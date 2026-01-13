"""FastAPI application for workflow execution."""

import base64
import json
import logging
import os
import traceback
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from io import StringIO
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import ruamel.yaml
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from opentelemetry import trace as otel_trace
from pydantic import BaseModel, Field, SecretStr
from rattler import MatchSpec
from wt_invokers import (
    AbstractInvoker,
    CloudBatchInvoker,
    LocalSubprocessInvoker,
)

from wt_runner.tracing import (
    TraceContextHeaders,
    attach_context,
    build_context_headers,
    configure_tracer,
    make_otel_console_exporter_file_dst_kws,
)

# Optional imports for ecoscope integration
try:
    from ecoscope_eda_core.messages.commands import (
        InvokerType as EcoscopeInvokerType,
    )
    from ecoscope_eda_core.messages.commands import (
        RunWorkflow,
        RunWorkflowParams,
    )
    from ecoscope_eda_core.workflows import get_results_json as ecoscope_get_results_json

    HAS_ECOSCOPE = True
    InvokerType = EcoscopeInvokerType
except ImportError:
    HAS_ECOSCOPE = False
    # Define InvokerType locally when ecoscope_eda_core is not available
    InvokerType = Literal[
        "BlockingLocalSubprocessInvoker",
        "AsyncLocalSubprocessInvoker",
        "CloudBatchInvoker",
    ]
    RunWorkflow = None  # type: ignore
    RunWorkflowParams = None  # type: ignore
    ecoscope_get_results_json = None  # type: ignore

# Optional import for storage
try:
    import obstore

    HAS_OBSTORE = True
except ImportError:
    HAS_OBSTORE = False
    obstore = None  # type: ignore

# Invoker registry mapping invoker names to classes
INVOKERS: dict[str, type[AbstractInvoker]] = {
    "BlockingLocalSubprocessInvoker": LocalSubprocessInvoker,
    "AsyncLocalSubprocessInvoker": LocalSubprocessInvoker,
    "CloudBatchInvoker": CloudBatchInvoker,
}

TITLE = "wt-runner"
TIMEOUT_EXPIRED_ERROR_MSG = (
    "The workflow timed out. Consider reducing the amount of data being processed."
)
PUBSUB_ACK_MAX_TIMEOUT = 570  # seconds


async def get_results_json(results_url: str) -> dict:
    """Get workflow results from results URL.

    Args:
        results_url: URL or path to results

    Returns:
        Results dictionary

    Raises:
        RuntimeError: If results cannot be retrieved
    """
    if HAS_ECOSCOPE and ecoscope_get_results_json is not None:
        return await ecoscope_get_results_json(results_url)

    # Fallback implementation for when ecoscope_eda_core is not available
    if not HAS_OBSTORE:
        raise RuntimeError(
            "Cannot retrieve results: neither ecoscope_eda_core nor obstore is available"
        )

    store = obstore.store.from_url(results_url)
    result_bytes = await store.get_async("result.json")
    return json.loads(result_bytes.decode("utf-8"))


def get_otel_exporter() -> Literal["console", "gcp"] | None:
    """Get OpenTelemetry exporter type from environment.

    Returns:
        Exporter type or None
    """
    return os.environ.get("ECOSCOPE_WORKFLOWS_OTEL_EXPORTER")


def get_otel_console_exporter_dst() -> Literal["stdout", "file"]:
    """Get console exporter destination from environment.

    Returns:
        Destination type (stdout or file)
    """
    return os.environ.get("ECOSCOPE_WORKFLOWS_OTEL_CONSOLE_EXPORTER_DST", "file")


def get_otel_console_exporter_file_dst_target_dir() -> str | None:
    """Get console exporter file destination directory from environment.

    Returns:
        Target directory path or None
    """
    return os.environ.get("ECOSCOPE_WORKFLOWS_OTEL_CONSOLE_EXPORTER_FILE_DST_TARGET_DIR")


@dataclass
class SpanAttributes:
    """Attributes for tracing spans."""

    workflow_run_id: str
    invoker_type: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup/shutdown.

    Configures OpenTelemetry tracer on startup.

    Args:
        app: FastAPI application instance
    """
    # on app startup
    otel_exporter_kws: dict = {}
    otel_exporter = get_otel_exporter()
    if otel_exporter == "console" and get_otel_console_exporter_dst() == "file":
        if not (file_dst_target_dir := get_otel_console_exporter_file_dst_target_dir()):
            raise RuntimeError(
                "If OTEL_EXPORTER is 'console' with the destination as 'file', "
                "then OTEL_CONSOLE_EXPORTER_FILE_DST_TARGET_DIR must be set via the "
                "env var 'ECOSCOPE_WORKFLOWS_OTEL_CONSOLE_EXPORTER_FILE_DST_TARGET_DIR'."
            )
        otel_exporter_kws |= make_otel_console_exporter_file_dst_kws(Path(file_dst_target_dir))
    configure_tracer(
        name=app.title,
        version=app.version,
        exporter=otel_exporter,
        exporter_kws=otel_exporter_kws,
    )
    yield
    # on app shutdown


try:
    _version = version(TITLE)
except PackageNotFoundError:
    _version = "unknown"

app = FastAPI(title=TITLE, version=_version, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["POST"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


class Lithops(BaseModel):
    """Lithops configuration."""

    backend: Literal["localhost", "gcp_cloudrun"] = "localhost"
    storage: Literal["localhost", "gcp_storage"] = "localhost"
    log_level: str = "DEBUG"
    data_limit: int = 256


class GCP(BaseModel):
    """Google Cloud Platform configuration."""

    region: str = "us-central1"
    credentials_path: str = "placeholder"  # os.environ["GOOGLE_APPLICATION_CREDENTIALS"]


class GCPCloudRun(BaseModel):
    """Google Cloud Run configuration."""

    runtime: str = "placeholder"  # os.environ["LITHOPS_GCP_CLOUDRUN_RUNTIME"]
    runtime_cpu: int = 2
    runtime_memory: int = 1000


class LithopsConfig(BaseModel):
    """Complete Lithops configuration."""

    lithops: Lithops = Field(default_factory=Lithops)
    gcp: GCP | None = None
    gcp_cloudrun: GCPCloudRun | None = None


class ResponseModel(BaseModel):
    """Standard response model for workflow execution."""

    result: dict | None = None
    error: str | None = None
    trace: str | None = None


@app.get("/", status_code=200)
def health_check():
    """Health check endpoint.

    Returns:
        Status dictionary
    """
    return {"status": "ok"}


def resolve_matchspec(
    matchspec: str | None = Query(None, description="Matchspec for the workflow."),
) -> MatchSpec:
    """Get the matchspec for the workflow.

    Args:
        matchspec: Rattler matchspec string

    Returns:
        Parsed MatchSpec object

    Raises:
        ValueError: If matchspec is not provided
    """
    matchspec_override = os.environ.get("ECOSCOPE_WORKFLOWS_MATCHSPEC_OVERRIDE")
    matchspec_str = matchspec_override or matchspec
    if not matchspec_str:
        raise ValueError("Query param `matchspec` is required.")
    return MatchSpec(matchspec_str)


async def resolve_invoker(
    invoker_type: InvokerType = Query("BlockingLocalSubprocessInvoker"),
    matchspec: MatchSpec = Depends(resolve_matchspec),
) -> AbstractInvoker:
    """Resolves the invoker name to the corresponding invoker class.

    Args:
        invoker_type: Type of invoker to use
        matchspec: Workflow matchspec

    Returns:
        Configured and installed invoker instance

    Raises:
        ValueError: If unknown invoker type specified
    """
    if invoker_type not in INVOKERS:
        raise ValueError(f"Unknown invoker name: {invoker_type}")

    invoker = INVOKERS[invoker_type](matchspec=matchspec)
    is_installed = await invoker.is_installed()
    if not is_installed:
        await invoker.install()

    return invoker


def resolve_results_url(
    results_url: str = Query(..., description="Results URL for the workflow."),
) -> str:
    """Get the results URL for the workflow.

    Args:
        results_url: URL or local path for results

    Returns:
        Normalized results URL

    Raises:
        ValueError: If URL is invalid
    """
    if not urlparse(results_url).scheme:
        p = Path(results_url)
        if not p.is_absolute():
            raise ValueError("Results URL must be an absolute local path or a URL with scheme.")
        return p.as_uri()
    return results_url


@app.post("/", status_code=200, response_model=ResponseModel)
async def run(
    # service response
    response: Response,
    # user (http) inputs
    params: dict,
    execution_mode: Literal["async", "sequential"],
    mock_io: bool,
    results_url: str = Depends(resolve_results_url),
    data_connections_env_vars: dict[str, SecretStr] | None = None,
    lithops_config: LithopsConfig | None = None,
    invoker: AbstractInvoker = Depends(resolve_invoker),
    workflow_run_id: str = Query("", description="Unique ID for the workflow run."),
    timeout: float | None = Query(
        None,
        description="Timeout for the workflow in seconds. Defaults to null; i.e., no timeout.",
    ),
    docker_image_uri: str | None = Query(None, description="Docker image URI for the workflow."),
    traceparent: str | None = Header(
        None,
        description="Traceparent header; Cf. https://www.w3.org/TR/trace-context/.",
    ),
    tracestate: str | None = Header(
        None, description="Tracestate header; Cf. https://www.w3.org/TR/trace-context/."
    ),
):
    """Run a workflow with the specified parameters.

    Args:
        response: FastAPI response object
        params: Workflow parameters
        execution_mode: Execution mode (async or sequential)
        mock_io: Whether to mock I/O operations
        results_url: URL for storing results
        data_connections_env_vars: Environment variables for data connections
        lithops_config: Lithops configuration for async execution
        invoker: Workflow invoker instance
        workflow_run_id: Unique run identifier
        timeout: Timeout in seconds
        docker_image_uri: Docker image URI
        traceparent: W3C traceparent header
        tracestate: W3C tracestate header

    Returns:
        Workflow execution result
    """
    tracer = otel_trace.get_tracer(__name__)
    if traceparent:
        attach_context(traceparent, tracestate)
    span_attributes = SpanAttributes(
        workflow_run_id=workflow_run_id,
        invoker_type=type(invoker).__name__,
    )
    with tracer.start_as_current_span(
        "run-endpoint",
        attributes=asdict(span_attributes),
    ):
        yaml = ruamel.yaml.YAML(typ="safe")
        extra_env = {}
        if data_connections_env_vars:
            extra_env |= {k: v.get_secret_value() for k, v in data_connections_env_vars.items()}
        trace_context = build_context_headers()
        extra_env |= {k.upper(): v for k, v in trace_context.items()}
        config_text_stream = StringIO()
        yaml.dump(params, config_text_stream)
        lithops_kws = {}
        if execution_mode == "async":
            lithops_config = LithopsConfig() if not lithops_config else lithops_config
            lithops_text_stream = StringIO()
            yaml.dump(lithops_config.model_dump(), lithops_text_stream)
            lithops_kws = {"lithops_config_text": lithops_text_stream.getvalue()}
        try:
            await invoker.run(
                workflow_run_id=workflow_run_id,
                config_text=config_text_stream.getvalue(),
                results_url=results_url,
                execution_mode=execution_mode,
                mock_io=mock_io,
                extra_env=extra_env,
                otel_exporter=get_otel_exporter(),
                otel_console_exporter_dst=get_otel_console_exporter_dst(),
                **lithops_kws,
                docker_image_uri=docker_image_uri,
            )
            if invoker.is_waitable:
                await invoker.wait(timeout=timeout, error_msg=TIMEOUT_EXPIRED_ERROR_MSG)
                result = await get_results_json(results_url)
            else:
                result = {"result": {}, "error": None, "trace": None}
                return JSONResponse(content=result, status_code=status.HTTP_202_ACCEPTED)
        except Exception as e:
            trace = traceback.format_exc()
            result = {"error": str(e), "trace": trace}

        if not isinstance(result, dict):
            raise RuntimeError(f"Unexpected {result = }. Expected dict.")

        if result.get("result") is None and result.get("error") is not None:
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

        return result


@app.post(
    "/run-from-pubsub",
    summary="Processes RunWorkflow messages from Pub/Sub",
    status_code=200,
)
async def run_from_pubsub(
    request: Request,
):
    """Process RunWorkflow messages from Google Cloud Pub/Sub.

    Note: Requires ecoscope_eda_core to be installed.

    Args:
        request: FastAPI request object containing Pub/Sub message

    Returns:
        Status dictionary

    Raises:
        HTTPException: If ecoscope_eda_core is not available
    """
    if not HAS_ECOSCOPE:
        raise HTTPException(
            status_code=501,
            detail="Pub/Sub endpoint requires ecoscope_eda_core to be installed",
        )

    try:  # Extract the payload from the PubSub message
        command_payload = await extract_payload_from_pubsub_request(request)
        invoker_params, trace_context = prepare_invoker_parameters(command_payload)
    except (base64.binascii.Error, json.JSONDecodeError, ValueError) as e:
        # handle invalid payload errors to avoid 500 errors,
        # since it doesn't make sense to let GCP retry those
        trace = traceback.format_exc()
        error_msg = f"Error extracting data from PubSub message: {type(e).__name__}: {e}"
        logging.exception(error_msg)
        return {
            "status": "error",
            "error": error_msg,
            "trace": trace,
        }  # Error details are returned for local debugging

    tracer = otel_trace.get_tracer(__name__)
    if trace_context and (traceparent := trace_context.get("traceparent")) is not None:
        attach_context(traceparent, tracestate=trace_context.get("tracestate"))
    span_attributes = SpanAttributes(
        workflow_run_id=invoker_params.get("workflow_run_id", ""),
        invoker_type=command_payload.invoker_type,
    )
    with tracer.start_as_current_span(
        "run-from-pubsub-endpoint",
        attributes=asdict(span_attributes),
    ):
        trace_context = build_context_headers()
        invoker_params["extra_env"] |= {k.upper(): v for k, v in trace_context.items()}
        invoker_params["otel_exporter"] = get_otel_exporter()
        invoker_params["otel_console_exporter_dst"] = get_otel_console_exporter_dst()
        try:  # Resolve the invoker
            match_spec_obj = resolve_matchspec(matchspec=command_payload.match_spec)
            invoker = await resolve_invoker(
                invoker_type=command_payload.invoker_type, matchspec=match_spec_obj
            )
        except ValueError as e:
            trace = traceback.format_exc()
            error = {"error": str(e), "trace": trace}
            await upload_error_to_gcs(
                error_details=error, results_url=invoker_params["results_url"]
            )
            return {"status": "error", **error}

        try:
            await invoker.run(**invoker_params)
            if invoker.is_waitable:
                timeout = command_payload.invoker_kwargs.get("timeout", PUBSUB_ACK_MAX_TIMEOUT)
                # Maximum timeout when running from PubSub is 10 minutes.
                # It's set to a little bit less to have time to cancel and handle the error
                timeout = min(timeout, max(timeout, PUBSUB_ACK_MAX_TIMEOUT))
                exit_code = await invoker.wait(timeout=timeout, error_msg=TIMEOUT_EXPIRED_ERROR_MSG)
                if exit_code != 0:
                    raise RuntimeError(f"Workflow invoker failed with exit code {exit_code}.")
        except Exception as e:
            trace = traceback.format_exc()
            error = {"error": f"{type(e).__name__}: {e}", "trace": trace}
            await upload_error_to_gcs(
                error_details=error, results_url=invoker_params["results_url"]
            )
            return {"status": "error", **error}

        return {"status": "processed"}


async def extract_payload_from_pubsub_request(
    request: Request,
) -> RunWorkflowParams:
    """Extract the payload from the PubSub request.

    Args:
        request: FastAPI request object

    Returns:
        Parsed workflow parameters

    Raises:
        json.JSONDecodeError: If JSON is invalid
        base64.binascii.Error: If base64 decoding fails
    """
    request_data = await request.json()
    message = request_data.get("message", {})
    payload = base64.b64decode(message.get("data", "{}").encode("utf-8"))
    json_payload = json.loads(payload)
    command = RunWorkflow.model_validate(json_payload)
    return command.payload


def prepare_invoker_parameters(
    command_payload: RunWorkflowParams,
) -> tuple[dict[str, Any], TraceContextHeaders]:
    """Prepare parameters for the invoker from the command payload.

    Args:
        command_payload: Workflow parameters from Pub/Sub message

    Returns:
        Tuple of (invoker_params, trace_context)
    """
    invoker_kwargs = command_payload.invoker_kwargs
    workflow_run_id = invoker_kwargs.pop("workflow_run_id", "")
    results_url = invoker_kwargs.pop("results_url", None)
    params = invoker_kwargs.pop("params", {})
    data_connections_env_vars = invoker_kwargs.pop("data_connections_env_vars", {})
    # at minimum, should contain `traceparent`, optionally `tracestate`
    trace_context = invoker_kwargs.pop("trace_context", None)
    execution_mode = invoker_kwargs.pop("execution_mode", "sequential")
    mock_io = invoker_kwargs.pop("mock_io", False)
    # Build extra params needed for the invoker
    yaml = ruamel.yaml.YAML(typ="safe")
    config_text_stream = StringIO()
    yaml.dump(params, config_text_stream)
    lithops_kws = {}
    if execution_mode == "async":
        lithops_config = LithopsConfig()
        lithops_text_stream = StringIO()
        yaml.dump(lithops_config.model_dump(), lithops_text_stream)
        lithops_kws = {"lithops_config_text": lithops_text_stream.getvalue()}
    return (
        {
            "workflow_run_id": workflow_run_id,
            "config_text": config_text_stream.getvalue(),
            "results_url": results_url,
            "execution_mode": execution_mode,
            "mock_io": mock_io,
            "extra_env": data_connections_env_vars,
        }
        | lithops_kws
        | invoker_kwargs,
        trace_context,
    )  # Extra kwargs are passed to the invoker


async def upload_error_to_gcs(error_details: dict, results_url: str) -> None:
    """Upload error details to Google Cloud Storage.

    Args:
        error_details: Error information dictionary
        results_url: URL for storing results

    Raises:
        RuntimeError: If obstore is not available
    """
    if not HAS_OBSTORE:
        raise RuntimeError("Cannot upload error: obstore is not available")

    # Save error in result.json and upload to GCS
    result_store = obstore.store.from_url(results_url)
    result_bytes = json.dumps(error_details).encode("utf-8")
    await result_store.put_async("result.json", result_bytes)


async def _get_metadata_attribute(
    attr: str,
    invoker: AbstractInvoker,
) -> dict:
    """Get a metadata attribute for the workflow.

    Args:
        attr: Attribute name to retrieve
        invoker: Invoker instance

    Returns:
        Metadata as dictionary

    Raises:
        RuntimeError: If attribute retrieval or parsing fails
    """
    out = await invoker.check_output(f"get {attr}".split())
    if not out:
        raise RuntimeError(f"Failed to get {attr}.")
    try:
        as_json = json.loads(out)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse rjsf from str: {out}") from e
    return as_json


@app.get("/rjsf", status_code=200)
async def rjsf(invoker: AbstractInvoker = Depends(resolve_invoker)):
    """Get the React JSON Schema Form schema for the workflow.

    Args:
        invoker: Invoker instance

    Returns:
        RJSF schema dictionary
    """
    return await _get_metadata_attribute("rjsf", invoker)


@app.get("/data-connection-property-names", status_code=200)
async def data_connection_property_names(
    invoker: AbstractInvoker = Depends(resolve_invoker),
):
    """Get the data connection property names for the workflow.

    Args:
        invoker: Invoker instance

    Returns:
        Data connection property names
    """
    return await _get_metadata_attribute("data-connection-property-names", invoker)


async def _convert(
    from_: str,
    to: str,
    json_: str,
    invoker: AbstractInvoker,
) -> dict:
    """Convert between params and formdata, and visa-versa.

    Args:
        from_: Source format
        to: Target format
        json_: JSON string to convert
        invoker: Invoker instance

    Returns:
        Converted data as dictionary

    Raises:
        RuntimeError: If conversion or parsing fails
    """
    cmd = f"convert --from {from_} --to {to}"
    out = await invoker.check_output(cmd.split(), stdin=json_)
    if not out:
        raise RuntimeError(f"Failed to convert {from_} to {to} for '{json_}'.")
    try:
        as_json = json.loads(out)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse rjsf from str: {out}") from e
    return as_json


def _is_422(json_: list[dict]) -> bool:
    """Check if the json is a 422 validation error.

    Args:
        json_: JSON data to check

    Returns:
        True if data represents a 422 error
    """
    return (
        isinstance(json_, list)
        and len(json_) > 0
        and all(isinstance(e, dict) for e in json_)
        and all(set(e) == {"type", "loc", "msg", "input", "url"} for e in json_)
    )


@app.post("/formdata-to-params", status_code=200)
async def validate_formdata(formdata: dict, invoker: AbstractInvoker = Depends(resolve_invoker)):
    """Convert and validate form data to workflow parameters.

    Args:
        formdata: Form data dictionary
        invoker: Invoker instance

    Returns:
        Validated parameters dictionary

    Raises:
        HTTPException: If validation fails (422 error)
    """
    outjson = await _convert(
        from_="formdata",
        to="params",
        json_=json.dumps(formdata),
        invoker=invoker,
    )
    if _is_422(outjson):
        raise HTTPException(status_code=422, detail=outjson)
    return outjson


@app.post("/params-to-formdata", status_code=200)
async def generate_nested_params(params: dict, invoker: AbstractInvoker = Depends(resolve_invoker)):
    """Convert workflow parameters to form data format.

    Args:
        params: Parameters dictionary
        invoker: Invoker instance

    Returns:
        Form data dictionary

    Raises:
        HTTPException: If conversion fails (422 error)
    """
    outjson = await _convert(
        from_="params",
        to="formdata",
        json_=json.dumps(params),
        invoker=invoker,
    )
    if _is_422(outjson):
        raise HTTPException(status_code=422, detail=outjson)
    return outjson

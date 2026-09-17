"""FastAPI service that keeps the task registry hot and compiles specs on demand.

At startup the service discovers tasks *in process* once
(:func:`~wt_compiler.discovery.populate_known_tasks_in_process`), paying the
heavy task-stack import (e.g. ``ecoscope.platform``) a single time. The request
path is then free of it, so warm compiles complete in tens of milliseconds.

The compile and run steps are split around a persistent on-disk build:

* ``POST /compile`` compiles a spec to a package on disk and returns a
  ``build_id`` (plus the rendered DAG and parameter schema).
* ``POST /run`` runs a build -- either an existing ``build_id`` (no recompile)
  or a spec to hot-compile and then run.

This is the "compile/run in the service" component of the on-the-fly invoker
design: an image that bakes in the ``wt`` stack + the task libraries serves
this app to turn specs into runnable DAGs cheaply.

Run (inside an environment with wt-compiler + wt-registry + the task
libraries installed)::

    uvicorn wt_compiler_service.app:app --host 0.0.0.0 --port 8099
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import ruamel.yaml
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from wt_compiler.discovery import populate_known_tasks_in_process

from wt_compiler_service import builder, runner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _configure_logging() -> None:
    """Attach an INFO stderr handler to the package logger, once.

    uvicorn only configures its own loggers, so application logs would be
    invisible by default; this makes the service's build/run logs show without
    touching the root logger or uvicorn's handlers.
    """
    pkg_logger = logging.getLogger("wt_compiler_service")
    if not pkg_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        pkg_logger.addHandler(handler)
        pkg_logger.setLevel(logging.INFO)
        pkg_logger.propagate = False


_configure_logging()

_yaml = ruamel.yaml.YAML(typ="safe")

# Warm state, populated once at startup and read by every compile request.
STATE: dict[str, Any] = {"n_tasks": 0, "warmup_seconds": None}


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Warm the registry once: import the task stack into this process.

    The heavy discovery import happens here, at startup, so the request path
    stays free of it. Records the warmup cost and task count in :data:`STATE`.

    Args:
        _app: The FastAPI application (unused).

    Yields:
        Control back to the running application after warmup completes.
    """
    t0 = time.monotonic()
    result = populate_known_tasks_in_process()
    STATE["warmup_seconds"] = round(time.monotonic() - t0, 3)
    STATE["n_tasks"] = sum(len(v) for v in result.tasks.values())
    yield


app = FastAPI(title="wt-compiler-service", lifespan=lifespan)


class CompileRequest(BaseModel):
    """A spec to compile, supplied inline as a dict or as YAML text."""

    spec: dict[str, Any] | None = None
    spec_yaml: str | None = None
    variant: str | None = None
    pkg_name_prefix: str = "wt"


class CompileResponse(BaseModel):
    """A persisted build: its id, version, rendered DAG, schema, and timing."""

    build_id: str
    release_name: str
    package_name: str
    version: str
    dag: str
    params_schema: dict[str, Any]
    n_tasks_in_workflow: int
    compile_ms: float
    cached: bool


@app.get("/")
def health() -> dict[str, Any]:
    """Report warm state: whether the registry is hot and its warmup cost.

    Returns:
        A mapping with the hot/cold status, the number of registered tasks,
        and the one-time warmup duration in seconds.
    """
    return {
        "status": "hot" if STATE["n_tasks"] else "cold",
        "n_tasks_registered": STATE["n_tasks"],
        "warmup_seconds": STATE["warmup_seconds"],
    }


@app.post("/compile", response_model=CompileResponse)
def compile_spec(req: CompileRequest) -> CompileResponse:
    """Compile a spec against the hot registry to a persistent build on disk.

    The compiled package is written to disk and registered under a ``build_id``
    that :func:`run_spec` can later run without recompiling.

    Args:
        req: The compile request carrying the spec (as a dict or YAML text)
            and compile options.

    Returns:
        The build id, rendered DAG, parameter schema, and compile timing.

    Raises:
        HTTPException: 422 if not exactly one of ``spec``/``spec_yaml`` is
            given; 400 if validation or compilation fails.
    """
    if (req.spec is None) == (req.spec_yaml is None):
        raise HTTPException(status_code=422, detail="Provide exactly one of `spec` or `spec_yaml`.")
    data = req.spec if req.spec is not None else _yaml.load(req.spec_yaml)

    t0 = time.monotonic()
    try:
        build, cached = builder.build(
            data, variant=req.variant, pkg_name_prefix=req.pkg_name_prefix
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}") from e
    compile_ms = round((time.monotonic() - t0) * 1000, 1)

    return CompileResponse(
        build_id=build.build_id,
        release_name=build.release_name,
        package_name=build.package_name,
        version=build.version,
        dag=build.dag,
        params_schema=build.params_schema,
        n_tasks_in_workflow=build.n_tasks,
        compile_ms=compile_ms,
        cached=cached,
    )


class RunRequest(BaseModel):
    """Params to run, plus exactly one of a ``build_id`` or a spec to compile."""

    build_id: str | None = None
    spec: dict[str, Any] | None = None
    spec_yaml: str | None = None
    params: dict[str, Any] = {}
    execution_mode: str = "sequential"
    mock_io: bool = False
    variant: str | None = None
    pkg_name_prefix: str = "wt"
    env: dict[str, str] | None = None
    timeout: float | None = None
    results_url: str | None = None


class RunResponse(BaseModel):
    """The workflow response envelope plus build identity and timing."""

    build_id: str
    release_name: str
    version: str
    results_url: str
    result: Any = None
    error: str | None = None
    trace: str | None = None
    compile_ms: float
    run_ms: float
    returncode: int
    cached: bool


@app.post("/run", response_model=RunResponse)
async def run_spec(req: RunRequest) -> RunResponse:
    """Run a compiled build -- from an existing ``build_id`` or by hot-compiling a spec.

    Provide exactly one of ``build_id`` (run a build already on disk),
    ``spec``, or ``spec_yaml`` (hot-compile, then run). Execution is an isolated
    subprocess in the shared environment. Task-level failures are returned in
    ``error`` with a 200 status (mirroring the workflow response envelope); only
    compilation or validation failures produce a 400.

    Args:
        req: The run request carrying the build id or spec, params, and options.

    Returns:
        The workflow result envelope with build identity and compile/run timings.

    Raises:
        HTTPException: 422 if not exactly one of ``build_id``/``spec``/
            ``spec_yaml`` is given; 404 if ``build_id`` is unknown; 400 if
            compilation or spec validation fails.
    """
    if sum(x is not None for x in (req.build_id, req.spec, req.spec_yaml)) != 1:
        raise HTTPException(
            status_code=422,
            detail="Provide exactly one of `build_id`, `spec`, or `spec_yaml`.",
        )

    t0 = time.monotonic()
    if req.build_id is not None:
        resolved = builder.get_build(req.build_id)
        if resolved is None:
            raise HTTPException(status_code=404, detail=f"Unknown build_id: {req.build_id}")
        build, cached = resolved, True
    else:
        data = req.spec if req.spec is not None else _yaml.load(req.spec_yaml)
        try:
            build, cached = await run_in_threadpool(
                builder.build, data, variant=req.variant, pkg_name_prefix=req.pkg_name_prefix
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}") from e
    compile_ms = round((time.monotonic() - t0) * 1000, 1)

    outcome = await runner.run_build(
        build.release_dir,
        build.package_name,
        req.params,
        execution_mode=req.execution_mode,
        mock_io=req.mock_io,
        env=req.env,
        timeout=req.timeout,
        results_url=req.results_url,
        results_env_var=build.results_env_var,
    )
    return RunResponse(
        build_id=build.build_id,
        release_name=build.release_name,
        version=build.version,
        compile_ms=compile_ms,
        cached=cached,
        **outcome,
    )

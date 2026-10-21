"""Tests for the generated workflow CLI's span flushing on exit and SIGTERM."""

import ast
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

import wt_compiler

TEMPLATES = Path(wt_compiler.__file__).parent / "templates"


def _render_cli() -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), keep_trailing_newline=True)  # noqa: S701
    return env.get_template("pkg/cli.jinja2").render(
        file_header="# generated",
        release_name="wt-demo-workflow",
        results_env_var="ECOSCOPE_WORKFLOWS_RESULTS",
    )


def _function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(source, node) or ""


def test_run_flushes_spans_on_every_exit_path() -> None:
    source = _render_cli()
    run = next(
        n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == "run"
    )
    registers_handler = any(
        isinstance(n, ast.Call) and ast.unparse(n.func) == "signal.signal" for n in ast.walk(run)
    )
    flushes_in_finally = any(
        isinstance(n, ast.Try) and any("_flush_spans" in ast.unparse(stmt) for stmt in n.finalbody)
        for n in ast.walk(run)
    )

    assert registers_handler
    assert flushes_in_finally


def test_sigterm_runs_finally_blocks(tmp_path: Path) -> None:
    """SIGTERM's default action skips `finally`, which is where spans flush."""
    marker = tmp_path / "flushed"
    handler = _function_source(_render_cli(), "_exit_on_sigterm")
    script = textwrap.dedent(
        """
        import signal, sys, time
        from typing import Any
        {handler}
        signal.signal(signal.SIGTERM, _exit_on_sigterm)
        try:
            print("ready", flush=True)
            time.sleep(30)
        finally:
            open({marker!r}, "w").close()
        """
    ).format(handler=handler, marker=str(marker))
    child = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", script], stdout=subprocess.PIPE, text=True
    )
    assert child.stdout is not None
    assert child.stdout.readline().strip() == "ready"

    child.send_signal(signal.SIGTERM)
    returncode = child.wait(timeout=10)

    assert returncode == 128 + signal.SIGTERM
    assert marker.exists()


def test_flush_timeout_fits_inside_invoker_grace() -> None:
    """Invokers wait 10s between SIGTERM and SIGKILL; the flush must finish first."""
    tree = ast.parse(_render_cli())
    timeout_ms = next(
        n.value.value
        for n in tree.body
        if isinstance(n, ast.Assign)
        and ast.unparse(n.targets[0]) == "SPAN_FLUSH_TIMEOUT_MILLIS"
        and isinstance(n.value, ast.Constant)
    )

    assert timeout_ms / 1000 < 10

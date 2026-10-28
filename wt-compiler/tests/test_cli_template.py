"""Tests for the generated workflow CLI's span flushing on exit and SIGTERM."""

import ast
import importlib.metadata
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


def _release_version_in(release_dir: Path, version_yaml: str | None, release_name: str) -> str:
    """Run the generated `_release_version` from a package in `release_dir`, via PYTHONPATH."""
    pkg = release_dir / "wt_demo_workflow"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "probe.py").write_text(
        "from importlib.metadata import PackageNotFoundError, version\n"
        "from pathlib import Path\n"
        f"RELEASE_NAME = {release_name!r}\n"
        f"{_function_source(_render_cli(), '_release_version')}\n"
        "print(_release_version())\n"
    )
    if version_yaml is not None:
        (release_dir / "VERSION.yaml").write_text(version_yaml)
    out = subprocess.run(
        [sys.executable, "-m", "wt_demo_workflow.probe"],
        env={"PYTHONPATH": str(release_dir)},
        cwd=release_dir.parent.parent,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def test_version_falls_back_to_version_yaml_when_not_installed(tmp_path: Path) -> None:
    """A compiled package run from its release dir has no installed metadata to read."""
    version = _release_version_in(
        tmp_path / "rel", "{MAJ: 19, MIN: 1, PATCH: 0}\n", "wt-demo-workflow"
    )

    assert version == "19.1.0"


def test_version_is_unknown_without_version_yaml(tmp_path: Path) -> None:
    assert _release_version_in(tmp_path / "rel", None, "wt-demo-workflow") == "unknown"
    assert _release_version_in(tmp_path / "bad", "[1, 2]\n", "wt-demo-workflow") == "unknown"


def test_installed_metadata_takes_precedence(tmp_path: Path) -> None:
    """An installed distribution's version wins over VERSION.yaml."""
    installed = _release_version_in(tmp_path / "rel", "{MAJ: 0, MIN: 0}\n", "pydantic")

    assert installed == importlib.metadata.version("pydantic")

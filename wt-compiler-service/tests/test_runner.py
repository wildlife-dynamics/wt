"""Tests for the runner: run a compiled build via CompiledPackageInvoker (mocked)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from wt_compiler_service import runner


def _fake_invoker() -> MagicMock:
    inv = MagicMock()
    inv.run = AsyncMock()
    inv.wait = AsyncMock(return_value=0)
    inv.run_state = {}
    return inv


async def test_run_build_drives_invoker():
    inv = _fake_invoker()
    envelope = {"result": 42, "error": None, "trace": None}
    with (
        patch.object(runner, "CompiledPackageInvoker", return_value=inv) as inv_cls,
        patch.object(runner, "_read_result", return_value=envelope),
    ):
        out = await runner.run_build(
            Path("/build/wt-demo-workflow"), "wt_demo_workflow", {"a": 1}, mock_io=True
        )

    inv_cls.assert_called_once()
    assert inv_cls.call_args.kwargs["package_name"] == "wt_demo_workflow"
    assert inv_cls.call_args.kwargs["results_env_var"] == "WT_RESULTS"  # default
    inv.run.assert_awaited_once()
    assert inv.run.call_args.kwargs["mock_io"] is True
    inv.wait.assert_awaited_once()
    assert out["result"] == 42
    assert out["returncode"] == 0
    assert out["results_url"].startswith("file://")


async def test_run_build_honors_provided_results_url():
    inv = _fake_invoker()
    with (
        patch.object(runner, "CompiledPackageInvoker", return_value=inv),
        patch.object(runner, "_read_result", return_value={"result": 1}),
    ):
        out = await runner.run_build(Path("/b"), "pkg", {}, results_url="file:///custom/results")

    assert out["results_url"] == "file:///custom/results"
    assert inv.run.call_args.kwargs["results_url"] == "file:///custom/results"


async def test_run_build_passes_results_env_var_to_invoker():
    inv = _fake_invoker()
    with (
        patch.object(runner, "CompiledPackageInvoker", return_value=inv) as inv_cls,
        patch.object(runner, "_read_result", return_value={"result": 1}),
    ):
        await runner.run_build(
            Path("/b"), "pkg", {}, results_env_var="ECOSCOPE_WORKFLOWS_RESULTS"
        )
    assert inv_cls.call_args.kwargs["results_env_var"] == "ECOSCOPE_WORKFLOWS_RESULTS"


def test_read_result_reads_file(tmp_path):
    (tmp_path / "result.json").write_text('{"result": 7, "error": null, "trace": null}')
    envelope = runner._read_result(tmp_path.as_uri())
    assert envelope["result"] == 7


def test_read_result_missing_returns_none(tmp_path):
    assert runner._read_result(tmp_path.as_uri()) is None

"""Tests for SandboxInvoker and its CLI entry point.

The full ``SandboxInvoker`` end-to-end path requires ``pixi-unpack`` and a
real environment tarball, which is out of scope for unit tests. Here we
verify the command construction, lifecycle hooks, and CLI argument parsing
with all external calls mocked.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
from rattler import MatchSpec

from wt_invokers.exceptions import EnvironmentTarDigestError, InvocationTimeoutError
from wt_invokers.sandbox import SandboxInvoker, _build_arg_parser, main

if TYPE_CHECKING:
    from pathlib import Path


def _digest(data: bytes) -> str:
    """sha256 of ``data`` in the ``sha256:<hex>`` form the invoker expects."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


# A syntactically valid digest for CLI tests where the value is never hashed.
_VALID_DIGEST = "sha256:" + "a" * 64


def test_initialization_default_work_dir() -> None:
    invoker = SandboxInvoker(matchspec=MatchSpec("w>=1.0.0"))
    assert invoker.work_dir == "/work"


def test_initialization_env_override() -> None:
    with patch.dict(
        os.environ, {"WT_INVOKERS__SANDBOX_INVOKER__WORK_DIR": "/custom/work"}
    ):
        invoker = SandboxInvoker(matchspec=MatchSpec("w>=1.0.0"))
        assert invoker.work_dir == "/custom/work"


def test_is_waitable() -> None:
    inv = SandboxInvoker(matchspec=MatchSpec("w>=1.0.0"))
    assert inv.is_waitable is True


@pytest.mark.asyncio
async def test_is_installed_returns_true() -> None:
    inv = SandboxInvoker(matchspec=MatchSpec("w>=1.0.0"))
    assert await inv.is_installed() is True


@pytest.mark.asyncio
async def test_install_raises() -> None:
    inv = SandboxInvoker(matchspec=MatchSpec("w>=1.0.0"))
    with pytest.raises(NotImplementedError, match="must be bundled"):
        await inv.install()


def test_workflow_name_from_matchspec() -> None:
    inv = SandboxInvoker(matchspec=MatchSpec("my-workflow>=1.0.0"))
    assert inv._workflow_name() == "my-workflow"


@pytest.mark.asyncio
async def test_run_without_activate_path_raises(tmp_path: Path) -> None:
    """Calling _run directly (no _pre_run) should raise since no activate_path."""
    inv = SandboxInvoker(matchspec=MatchSpec("w>=1.0.0"), work_dir=str(tmp_path))
    with pytest.raises(RuntimeError, match="activate_path not set"):
        await inv._run(
            workflow_run_id="r",
            config_text="k: v",
            results_url="file:///results",
            execution_mode="sequential",
            mock_io=False,
        )


@pytest.mark.asyncio
async def test_run_builds_expected_argv(tmp_path: Path) -> None:
    inv = SandboxInvoker(
        matchspec=MatchSpec("my-workflow>=1.0.0"), work_dir=str(tmp_path)
    )
    # Short-circuit the PixiUnpackMixin pre-run so we can focus on _run.
    inv.run_state["activate_path"] = "/fake/activate.sh"

    mock_proc = MagicMock()
    with patch("wt_invokers.sandbox.subprocess.Popen", return_value=mock_proc) as mp:
        await inv._run(
            workflow_run_id="r1",
            config_text="k: v",
            results_url="file:///results",
            execution_mode="sequential",
            mock_io=True,
            otel_exporter="http://localhost:4318",
            extra_env={"CUSTOM": "yes"},
        )

    cmd = mp.call_args[0][0]
    kwargs = mp.call_args[1]
    # argv form: no shell interpolation, no injection surface.
    assert isinstance(cmd, list)
    assert cmd[:4] == ["sh", "-c", '. "$1" && shift && exec "$@"', "sh"]
    assert "/fake/activate.sh" in cmd
    assert "my-workflow" in cmd
    assert "run" in cmd
    assert "--config-json" in cmd
    assert "--execution-mode" in cmd
    assert "sequential" in cmd
    assert "--mock-io" in cmd
    assert "--otel-exporter" in cmd
    assert "http://localhost:4318" in cmd
    assert kwargs["shell"] is False
    assert kwargs["cwd"] == str(tmp_path)
    # Inherit parent stdout/stderr — no PIPE that could deadlock wait().
    assert "stdout" not in kwargs
    assert "stderr" not in kwargs
    env = kwargs["env"]
    assert env[inv.results_env_var] == "file:///results"
    assert env["CUSTOM"] == "yes"


@pytest.mark.asyncio
async def test_run_no_mock_io_flag(tmp_path: Path) -> None:
    inv = SandboxInvoker(matchspec=MatchSpec("w>=1.0.0"), work_dir=str(tmp_path))
    inv.run_state["activate_path"] = "/a.sh"
    with patch("wt_invokers.sandbox.subprocess.Popen") as mp:
        await inv._run(
            workflow_run_id="r",
            config_text="k: v",
            results_url="file:///r",
            execution_mode="sequential",
            mock_io=False,
        )
    cmd = mp.call_args[0][0]
    assert "--no-mock-io" in cmd
    assert "--otel-exporter" not in cmd


@pytest.mark.asyncio
async def test_run_shell_metacharacters_in_fields_are_not_interpreted(
    tmp_path: Path,
) -> None:
    """Shell metacharacters in config/otel fields are positional args, not shell input.

    Regression test for the shell-injection surface that existed when ``_run``
    used ``shell=True`` with f-string interpolation. The argv-form invocation
    passes each field as its own positional argument, so no shell parsing of
    field content can occur.
    """
    inv = SandboxInvoker(matchspec=MatchSpec("w>=1.0.0"), work_dir=str(tmp_path))
    inv.run_state["activate_path"] = "/a.sh"
    hostile = "http://x?a=1&b=$(rm -rf /)"
    with patch("wt_invokers.sandbox.subprocess.Popen") as mp:
        await inv._run(
            workflow_run_id="r",
            config_text="k: v",
            results_url="file:///r",
            execution_mode="sequential",
            mock_io=False,
            otel_exporter=hostile,
        )
    cmd = mp.call_args[0][0]
    # Hostile value appears as a discrete argv entry, not wrapped in a shell
    # string. Any metacharacter is inert at this layer.
    assert hostile in cmd


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX sh required")
@pytest.mark.asyncio
async def test_run_actually_sources_activate_and_execs_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end check that _run's sh wrapper sources then execs correctly.

    Drives the *real* ``SandboxInvoker._run`` (no Popen mock). The fake
    ``activate.sh`` exports a marker env var; the fake workflow binary
    dumps its argv and the marker var to a file. Assertions prove:

    * the activation script was sourced (marker visible to exec'd prog),
    * the ``shift && exec`` pipeline passed argv through unmodified,
    * a hostile value in an optional arg arrived as a literal string,
      not shell-interpreted.

    If a future edit drops the ``shift``, flips ``$1`` / ``$@``, or
    re-introduces shell interpolation of fields, one of these asserts
    will fail.
    """
    activate = tmp_path / "activate.sh"
    activate.write_text("export WT_ACTIVATED=yes\n")

    dump = tmp_path / "dump.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_bin = bin_dir / "my-workflow"
    fake_bin.write_text(
        "#!/bin/sh\n"
        f'echo "ACT=$WT_ACTIVATED" > "{dump}"\n'
        f'for a in "$@"; do echo "ARG=$a" >> "{dump}"; done\n'
    )
    fake_bin.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    inv = SandboxInvoker(
        matchspec=MatchSpec("my-workflow>=1.0.0"), work_dir=str(tmp_path)
    )
    inv.run_state["activate_path"] = str(activate)

    hostile = "http://x?$(touch " + str(tmp_path / "pwned") + ")"
    await inv._run(
        workflow_run_id="r",
        config_text="k: v",
        results_url=f"file://{tmp_path}/out",
        execution_mode="sequential",
        mock_io=False,
        otel_exporter=hostile,
    )
    exit_code = inv.run_state["process"].wait(timeout=10)
    assert exit_code == 0

    contents = dump.read_text()
    assert "ACT=yes" in contents
    assert "ARG=run" in contents
    assert "ARG=sequential" in contents
    assert "ARG=--no-mock-io" in contents
    assert f"ARG={hostile}" in contents
    assert not (tmp_path / "pwned").exists()


@pytest.mark.asyncio
async def test_wait_returns_exit_code(tmp_path: Path) -> None:
    inv = SandboxInvoker(matchspec=MatchSpec("w>=1.0.0"), work_dir=str(tmp_path))
    mock_proc = MagicMock()
    mock_proc.wait.return_value = 0
    inv._is_running = True
    inv.run_state["process"] = mock_proc
    # short-circuit _post_run which needs run_args
    inv._run_args["results_url"] = f"file://{tmp_path}"
    # Provide a results dir so _post_run at least gets past its precondition
    results_dir = tmp_path / "r"
    results_dir.mkdir()
    inv._run_args["results_url"] = f"file://{results_dir}"
    inv._run_args["results_upload_url"] = f"file://{tmp_path}/out.tar.gz"
    code = await inv.wait()
    assert code == 0


@pytest.mark.asyncio
async def test_wait_timeout_raises(tmp_path: Path) -> None:
    inv = SandboxInvoker(matchspec=MatchSpec("w>=1.0.0"), work_dir=str(tmp_path))
    mock_proc = MagicMock()
    mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=1)
    inv._is_running = True
    inv.run_state["process"] = mock_proc
    results_dir = tmp_path / "r"
    results_dir.mkdir()
    inv._run_args["results_url"] = f"file://{results_dir}"
    inv._run_args["results_upload_url"] = f"file://{tmp_path}/out.tar.gz"
    with pytest.raises(InvocationTimeoutError):
        await inv.wait(timeout=1.0, error_msg="too long")


@pytest.mark.asyncio
async def test_wait_without_process_raises(tmp_path: Path) -> None:
    inv = SandboxInvoker(matchspec=MatchSpec("w>=1.0.0"), work_dir=str(tmp_path))
    inv._is_running = True
    # Populate run_args so _post_run's preconditions don't mask the error we
    # actually want to surface from _wait.
    results_dir = tmp_path / "r"
    results_dir.mkdir()
    inv._run_args["results_url"] = f"file://{results_dir}"
    inv._run_args["results_upload_url"] = f"file://{tmp_path}/out.tar.gz"
    with pytest.raises(RuntimeError, match="Process not started"):
        await inv.wait()


@pytest.mark.asyncio
async def test_end_to_end_lifecycle_with_mocked_externals(tmp_path: Path) -> None:
    """Exercise the full run → wait path with pixi-unpack and upload mocked."""
    source_tar = tmp_path / "env.tar"
    source_tar.write_bytes(b"fake")
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "result.json").write_text('{"ok": true}')
    upload_dest = tmp_path / "out.tar.gz"

    inv = SandboxInvoker(
        matchspec=MatchSpec("my-workflow>=1.0.0"),
        work_dir=str(tmp_path / "work"),
    )

    mock_proc = MagicMock()
    mock_proc.wait.return_value = 0

    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        patch("wt_invokers.mixins.subprocess.run"),
        patch("wt_invokers.sandbox.subprocess.Popen", return_value=mock_proc),
    ):
        await inv.run(
            workflow_run_id="r1",
            config_text="k: v",
            results_url=f"file://{results_dir}",
            execution_mode="sequential",
            mock_io=False,
            environment_tar_url=f"file://{source_tar}",
            environment_tar_digest=_digest(b"fake"),
            results_upload_url=f"file://{upload_dest}",
        )
        exit_code = await inv.wait()

    assert exit_code == 0
    assert upload_dest.exists()  # post-run uploaded the tarball
    assert inv.is_running is False


@pytest.mark.asyncio
async def test_end_to_end_lifecycle_with_skip_upload(tmp_path: Path) -> None:
    """With skip_results_archive_upload, wait() succeeds and nothing is uploaded."""
    source_tar = tmp_path / "env.tar"
    source_tar.write_bytes(b"fake")
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "result.json").write_text('{"ok": true}')

    inv = SandboxInvoker(
        matchspec=MatchSpec("my-workflow>=1.0.0"),
        work_dir=str(tmp_path / "work"),
    )

    mock_proc = MagicMock()
    mock_proc.wait.return_value = 0

    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        patch("wt_invokers.mixins.subprocess.run"),
        patch("wt_invokers.sandbox.subprocess.Popen", return_value=mock_proc),
    ):
        await inv.run(
            workflow_run_id="r1",
            config_text="k: v",
            results_url=f"file://{results_dir}",
            execution_mode="sequential",
            mock_io=False,
            environment_tar_url=f"file://{source_tar}",
            environment_tar_digest=_digest(b"fake"),
            skip_results_archive_upload=True,
        )
        exit_code = await inv.wait()

    assert exit_code == 0
    # No upload artifact was created anywhere under tmp_path.
    assert not list(tmp_path.rglob("*.tar.gz"))  # noqa: ASYNC240  # test-only local FS scan; no event loop at stake
    assert inv.is_running is False


@pytest.mark.asyncio
async def test_end_to_end_digest_mismatch_raises_before_unpack(tmp_path: Path) -> None:
    """A digest mismatch fails before unpack.

    ``run()`` raises :class:`EnvironmentTarDigestError`; pixi-unpack and the
    workflow ``Popen`` never run, no ``result.json`` is written, nothing is
    uploaded, and the invoker is reset to the IDLE state.
    """
    source_tar = tmp_path / "env.tar"
    source_tar.write_bytes(b"fake")
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    upload_dest = tmp_path / "out.tar.gz"

    inv = SandboxInvoker(
        matchspec=MatchSpec("my-workflow>=1.0.0"),
        work_dir=str(tmp_path / "work"),
    )

    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        patch("wt_invokers.mixins.subprocess.run") as mock_unpack,
        patch("wt_invokers.sandbox.subprocess.Popen") as mock_popen,
        pytest.raises(
            EnvironmentTarDigestError,
            match=r"environment\.tar integrity check failed",
        ),
    ):
        await inv.run(
            workflow_run_id="r1",
            config_text="k: v",
            results_url=f"file://{results_dir}",
            execution_mode="sequential",
            mock_io=False,
            environment_tar_url=f"file://{source_tar}",
            environment_tar_digest=_digest(b"WRONG"),
            results_upload_url=f"file://{upload_dest}",
        )

    # Neither pixi-unpack nor the workflow process ran.
    mock_unpack.assert_not_called()
    mock_popen.assert_not_called()
    # No result.json was written and nothing was uploaded.
    assert not (results_dir / "result.json").exists()
    assert not upload_dest.exists()
    # The invoker was reset to IDLE.
    assert inv.is_running is False


@pytest.mark.asyncio
async def test_post_run_skip_accepts_non_file_results_url(tmp_path: Path) -> None:
    """With the skip flag set, the file:// scheme validation is bypassed."""
    inv = SandboxInvoker(matchspec=MatchSpec("w>=1.0.0"), work_dir=str(tmp_path))
    inv._run_args["results_url"] = "gs://bucket/results"
    inv._run_args["skip_results_archive_upload"] = True
    await inv._post_run()  # no upload, no validation error


# ---------------------------------------------------------------------------
# check_output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_output_is_not_supported(tmp_path: Path) -> None:
    """Sandbox runs workflows in an isolated container, so the driver cannot
    introspect the environment via ``check_output``."""
    inv = SandboxInvoker(matchspec=MatchSpec("w>=1.0.0"), work_dir=str(tmp_path))
    with pytest.raises(NotImplementedError):
        await inv.check_output(["--help"])


# ---------------------------------------------------------------------------
# CLI main()
# ---------------------------------------------------------------------------


def _cli_args_without_upload_url() -> list[str]:
    """Required CLI args, minus ``--results-upload-url``."""
    return [
        "--matchspec",
        "w>=1.0.0",
        "--workflow-run-id",
        "r",
        "--environment-tar-url",
        "https://x/e.tar",
        "--environment-tar-digest",
        _VALID_DIGEST,
        "--config-json",
        "{}",
    ]


def test_cli_parses_required_args() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args(
        [
            "--matchspec",
            "my-wf>=1.0.0",
            "--workflow-run-id",
            "r1",
            "--environment-tar-url",
            "https://x/env.tar",
            "--environment-tar-digest",
            _VALID_DIGEST,
            "--results-upload-url",
            "https://x/out",
            "--config-json",
            '{"k": "v"}',
        ]
    )
    assert args.matchspec == "my-wf>=1.0.0"
    assert args.execution_mode == "sequential"
    assert args.mock_io is False
    assert args.results_url == "file:///results"
    assert args.environment_tar_digest == _VALID_DIGEST


def test_cli_mock_io_flag() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args(
        [
            "--matchspec",
            "w>=1.0.0",
            "--workflow-run-id",
            "r",
            "--environment-tar-url",
            "https://x/e.tar",
            "--environment-tar-digest",
            _VALID_DIGEST,
            "--results-upload-url",
            "https://x/o",
            "--config-json",
            "{}",
            "--mock-io",
        ]
    )
    assert args.mock_io is True


def test_cli_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_cli_missing_required_args_exits() -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code != 0


def test_cli_missing_environment_tar_digest_exits() -> None:
    """--environment-tar-digest is required on the sandbox CLI."""
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--matchspec",
                "w>=1.0.0",
                "--workflow-run-id",
                "r",
                "--environment-tar-url",
                "https://x/e.tar",
                "--results-upload-url",
                "https://x/o",
                "--config-json",
                "{}",
            ]
        )
    assert exc.value.code != 0


@pytest.mark.parametrize(
    "bad_digest",
    [
        pytest.param("not-a-digest", id="no-prefix"),
        pytest.param("md5:" + "a" * 32, id="wrong-algorithm"),
        pytest.param("sha256:" + "a" * 10, id="bad-hex-length"),
    ],
)
def test_cli_bad_digest_format_exits(bad_digest: str) -> None:
    """A malformed --environment-tar-digest funnels to parser.error (SystemExit)."""
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--matchspec",
                "w>=1.0.0",
                "--workflow-run-id",
                "r",
                "--environment-tar-url",
                "https://x/e.tar",
                "--environment-tar-digest",
                bad_digest,
                "--results-upload-url",
                "https://x/o",
                "--config-json",
                "{}",
            ]
        )
    assert exc.value.code != 0


def test_cli_main_invokes_run_and_wait(tmp_path: Path) -> None:
    """main() should create a SandboxInvoker, call run() then wait()."""
    called: dict[str, Any] = {}

    async def fake_run(self: Any, **kwargs: Any) -> None:
        called["run_kwargs"] = kwargs

    async def fake_wait(self: Any, *args: Any, **kwargs: Any) -> int:
        called["waited"] = True
        return 7

    with (
        patch.object(SandboxInvoker, "run", new=fake_run),
        patch.object(SandboxInvoker, "wait", new=fake_wait),
    ):
        exit_code = main(
            [
                "--matchspec",
                "my-wf>=1.0.0",
                "--workflow-run-id",
                "r1",
                "--environment-tar-url",
                f"file://{tmp_path}/env.tar",
                "--environment-tar-digest",
                _VALID_DIGEST,
                "--results-upload-url",
                f"file://{tmp_path}/out.tar.gz",
                "--results-url",
                f"file://{tmp_path}/results",
                "--config-json",
                '{"k": "v"}',
            ]
        )

    assert exit_code == 7
    assert called["waited"] is True
    assert called["run_kwargs"]["workflow_run_id"] == "r1"
    assert called["run_kwargs"]["environment_tar_url"] == f"file://{tmp_path}/env.tar"
    assert called["run_kwargs"]["environment_tar_digest"] == _VALID_DIGEST
    assert called["run_kwargs"]["results_upload_url"] == f"file://{tmp_path}/out.tar.gz"
    assert called["run_kwargs"]["skip_results_archive_upload"] is False


def test_cli_skip_upload_flag_defaults_false() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args(
        [*_cli_args_without_upload_url(), "--results-upload-url", "https://x/o"]
    )
    assert args.skip_results_archive_upload is False


def test_cli_skip_upload_flag_parses_true() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args(
        [
            *_cli_args_without_upload_url(),
            "--dangerously-skip-results-archive-upload",
        ]
    )
    assert args.skip_results_archive_upload is True
    assert args.results_upload_url is None


def test_cli_missing_results_upload_url_without_skip_exits() -> None:
    """--results-upload-url is still effectively required without the skip flag."""
    with pytest.raises(SystemExit) as exc:
        main(_cli_args_without_upload_url())
    assert exc.value.code != 0


def test_cli_skip_upload_mutually_exclusive_with_upload_url() -> None:
    with pytest.raises(SystemExit) as exc:
        main(
            [
                *_cli_args_without_upload_url(),
                "--results-upload-url",
                "https://x/o",
                "--dangerously-skip-results-archive-upload",
                "--results-url",
                "file:///real/dest",
            ]
        )
    assert exc.value.code != 0


@pytest.mark.parametrize(
    "results_url_args",
    [
        pytest.param([], id="results-url-omitted"),
        pytest.param(["--results-url", "file:///results"], id="results-url-explicit"),
    ],
)
def test_cli_skip_upload_rejects_default_results_url(
    results_url_args: list[str],
) -> None:
    """Skipping the upload requires --results-url to be a real destination."""
    with pytest.raises(SystemExit) as exc:
        main(
            [
                *_cli_args_without_upload_url(),
                "--dangerously-skip-results-archive-upload",
                *results_url_args,
            ]
        )
    assert exc.value.code != 0


def test_cli_main_skip_upload_happy_path(tmp_path: Path) -> None:
    """With the flag and a real --results-url, run() receives the skip kwarg."""
    called: dict[str, Any] = {}

    async def fake_run(self: Any, **kwargs: Any) -> None:
        called["run_kwargs"] = kwargs

    async def fake_wait(self: Any, *args: Any, **kwargs: Any) -> int:
        return 0

    with (
        patch.object(SandboxInvoker, "run", new=fake_run),
        patch.object(SandboxInvoker, "wait", new=fake_wait),
    ):
        exit_code = main(
            [
                *_cli_args_without_upload_url(),
                "--dangerously-skip-results-archive-upload",
                "--results-url",
                f"file://{tmp_path}/results",
            ]
        )

    assert exit_code == 0
    assert called["run_kwargs"]["skip_results_archive_upload"] is True
    assert called["run_kwargs"]["results_upload_url"] is None

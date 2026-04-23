"""Tests for PixiUnpackMixin and UploadResultsArchiveMixin.

These mixins plug into AbstractInvoker's hook system. They are tested in
isolation by constructing lightweight ad-hoc invokers, populating
``run_args`` and ``run_state`` directly, and invoking ``_pre_run`` /
``_post_run``. A local HTTP server fixture (``http_server``) is used for
integration coverage of the real httpx download/upload path; unit tests
mock httpx for fine-grained retry behaviour.
"""

from __future__ import annotations

import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import stamina
from rattler import MatchSpec

from wt_invokers import mixins
from wt_invokers.abstract import AbstractInvoker
from wt_invokers.exceptions import PixiUnpackError
from wt_invokers.mixins import (
    PixiUnpackMixin,
    RetryableHTTPError,
    UploadResultsArchiveMixin,
)


@pytest.fixture(autouse=True)
def _fast_stamina() -> None:
    """Disable stamina backoff globally for tests."""
    stamina.set_testing(True, attempts=3)


@dataclass
class _PixiUnpackOnly(PixiUnpackMixin, AbstractInvoker):
    """Minimal invoker composing only PixiUnpackMixin for isolated tests."""

    work_dir: str = "/tmp/work"

    async def is_installed(self) -> bool:
        return True

    async def install(self) -> None:
        pass

    async def _run(self, **kwargs: Any) -> None:
        pass

    async def _wait(
        self, timeout: float | None = None, error_msg: str | None = None
    ) -> int:
        return 0

    @property
    def is_waitable(self) -> bool:
        return True


@dataclass
class _UploadOnly(UploadResultsArchiveMixin, AbstractInvoker):
    """Minimal invoker composing only UploadResultsArchiveMixin."""

    work_dir: str = "/tmp/work"

    async def is_installed(self) -> bool:
        return True

    async def install(self) -> None:
        pass

    async def _run(self, **kwargs: Any) -> None:
        pass

    async def _wait(
        self, timeout: float | None = None, error_msg: str | None = None
    ) -> int:
        return 0

    @property
    def is_waitable(self) -> bool:
        return True


def _make_pixi(tmp_path: Path, **run_args: Any) -> _PixiUnpackOnly:
    inv = _PixiUnpackOnly(matchspec=MatchSpec("w>=1.0.0"), work_dir=str(tmp_path))
    inv._run_args.update(run_args)
    return inv


def _make_upload(tmp_path: Path, **run_args: Any) -> _UploadOnly:
    inv = _UploadOnly(matchspec=MatchSpec("w>=1.0.0"), work_dir=str(tmp_path))
    inv._run_args.update(run_args)
    return inv


# ---------------------------------------------------------------------------
# Shared transfer config defaults
# ---------------------------------------------------------------------------


def test_transfer_config_defaults() -> None:
    # Reloading the module would be more rigorous, but the defaults are
    # static — verify the resolved module attributes look reasonable.
    assert mixins.TRANSFER_MAX_ATTEMPTS == 5
    assert mixins.TRANSFER_RETRY_WAIT_INITIAL == 1.0
    assert mixins.TRANSFER_RETRY_WAIT_MAX == 60.0
    assert mixins.TRANSFER_CONNECT_TIMEOUT == 30.0
    assert mixins.TRANSFER_TIMEOUT == 1800.0
    assert mixins.TRANSFER_CHUNK_SIZE == 65536


# ---------------------------------------------------------------------------
# PixiUnpackMixin tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_run_raises_if_pixi_unpack_missing(tmp_path: Path) -> None:
    inv = _make_pixi(tmp_path, environment_tar_url="file:///doesnt-matter")
    with patch("wt_invokers.mixins.shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="pixi-unpack not found"):
            await inv._pre_run()


@pytest.mark.asyncio
async def test_pre_run_missing_env_url_raises(tmp_path: Path) -> None:
    inv = _make_pixi(tmp_path)
    with patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"):
        with pytest.raises(ValueError, match="environment_tar_url is required"):
            await inv._pre_run()


@pytest.mark.asyncio
async def test_pre_run_unsupported_scheme(tmp_path: Path) -> None:
    inv = _make_pixi(tmp_path, environment_tar_url="s3://bucket/env.tar")
    with patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"):
        with pytest.raises(ValueError, match="Unsupported scheme"):
            await inv._pre_run()


@pytest.mark.asyncio
async def test_pre_run_file_url_copies_and_unpacks(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    source_tar = source / "env.tar"
    source_tar.write_bytes(b"fake-tarball")

    work = tmp_path / "work"
    work.mkdir()

    inv = _make_pixi(
        work,
        environment_tar_url=f"file://{source_tar}",
    )

    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        patch("wt_invokers.mixins.subprocess.run") as mock_run,
    ):
        await inv._pre_run()

    assert (work / "environment.tar").read_bytes() == b"fake-tarball"
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0] == ["pixi-unpack", str(work / "environment.tar")]
    assert kwargs["check"] is True
    assert kwargs["cwd"] == str(work)
    assert inv.run_state["activate_path"] == str(work / "activate.sh")


@pytest.mark.asyncio
async def test_pre_run_pixi_unpack_failure_wraps_in_domain_exception(
    tmp_path: Path,
) -> None:
    """CalledProcessError from pixi-unpack is wrapped in PixiUnpackError.

    The captured exit code, stdout, and stderr are preserved on the wrapping
    exception so callers can inspect the failure without handling
    subprocess-specific types.
    """
    source_tar = tmp_path / "env.tar"
    source_tar.write_bytes(b"bad")
    inv = _make_pixi(tmp_path, environment_tar_url=f"file://{source_tar}")
    underlying = subprocess.CalledProcessError(
        2, "pixi-unpack", output=b"out", stderr=b"err"
    )
    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        patch("wt_invokers.mixins.subprocess.run", side_effect=underlying),
    ):
        with pytest.raises(PixiUnpackError) as excinfo:
            await inv._pre_run()

    assert excinfo.value.returncode == 2
    assert excinfo.value.stdout == b"out"
    assert excinfo.value.stderr == b"err"
    assert excinfo.value.__cause__ is underlying


@pytest.mark.asyncio
async def test_pre_run_https_download_integration(
    tmp_path: Path,
    http_server: tuple[str, Path, dict[str, int]],
) -> None:
    url, directory, _fail = http_server
    # Serve an environment tarball from the HTTP server.
    (directory / "env.tar").write_bytes(b"streamed-bytes")

    work = tmp_path / "work"
    work.mkdir()
    inv = _make_pixi(work, environment_tar_url=f"{url}/env.tar")

    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        patch("wt_invokers.mixins.subprocess.run") as mock_run,
    ):
        await inv._pre_run()

    assert (work / "environment.tar").read_bytes() == b"streamed-bytes"
    mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_pre_run_retries_on_5xx(
    tmp_path: Path,
    http_server: tuple[str, Path, dict[str, int]],
) -> None:
    url, directory, fail_state = http_server
    (directory / "env.tar").write_bytes(b"bytes-v1")
    fail_state["_fail_remaining"] = 1  # first GET returns 500, then succeeds

    work = tmp_path / "work"
    work.mkdir()
    inv = _make_pixi(work, environment_tar_url=f"{url}/env.tar")

    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        patch("wt_invokers.mixins.subprocess.run"),
    ):
        await inv._pre_run()

    assert (work / "environment.tar").read_bytes() == b"bytes-v1"


@pytest.mark.asyncio
async def test_pre_run_download_does_not_retry_on_4xx(tmp_path: Path) -> None:
    """A 4xx response surfaces immediately as HTTPStatusError (no retry)."""
    inv = _make_pixi(tmp_path, environment_tar_url="https://example.com/env.tar")

    response = httpx.Response(
        404,
        request=httpx.Request("GET", "https://example.com/env.tar"),
    )

    class FakeStream:
        def __init__(self, response: httpx.Response) -> None:
            self._response = response

        async def __aenter__(self) -> httpx.Response:
            return self._response

        async def __aexit__(self, *exc: Any) -> None:
            return None

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        def stream(self, method: str, url: str) -> FakeStream:
            return FakeStream(response)

    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        patch("wt_invokers.mixins.httpx.AsyncClient", FakeClient),
    ):
        with pytest.raises(httpx.HTTPStatusError):
            await inv._pre_run()


# ---------------------------------------------------------------------------
# UploadResultsArchiveMixin tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_run_missing_results_url(tmp_path: Path) -> None:
    inv = _make_upload(tmp_path, results_upload_url=f"file://{tmp_path}/out.tgz")
    with pytest.raises(ValueError, match="results_url is required"):
        await inv._post_run()


@pytest.mark.asyncio
async def test_post_run_missing_results_upload_url(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    inv = _make_upload(tmp_path, results_url=f"file://{results_dir}")
    with pytest.raises(ValueError, match="results_upload_url is required"):
        await inv._post_run()


@pytest.mark.asyncio
async def test_post_run_non_file_results_url_rejected(tmp_path: Path) -> None:
    inv = _make_upload(
        tmp_path,
        results_url="gs://bucket/results",
        results_upload_url=f"file://{tmp_path}/out.tgz",
    )
    with pytest.raises(ValueError, match="must be a file:// URL"):
        await inv._post_run()


@pytest.mark.asyncio
async def test_post_run_missing_results_dir(tmp_path: Path) -> None:
    inv = _make_upload(
        tmp_path,
        results_url=f"file://{tmp_path}/missing-dir",
        results_upload_url=f"file://{tmp_path}/out.tgz",
    )
    with pytest.raises(RuntimeError, match="Results directory does not exist"):
        await inv._post_run()


@pytest.mark.asyncio
async def test_post_run_file_upload_produces_valid_tarball(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "result.json").write_text('{"ok": true}')
    (results_dir / "subdir").mkdir()
    (results_dir / "subdir" / "inner.txt").write_text("hello")

    dest = tmp_path / "upload" / "results.tar.gz"
    inv = _make_upload(
        tmp_path,
        results_url=f"file://{results_dir}",
        results_upload_url=f"file://{dest}",
    )
    await inv._post_run()

    assert dest.exists()
    with tarfile.open(dest, "r:gz") as tar:
        names = set(tar.getnames())
    assert "result.json" in names
    # sub-directory contents present too
    assert any(n.startswith("subdir") for n in names)


@pytest.mark.asyncio
async def test_post_run_empty_results_dir_is_valid_tar(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    dest = tmp_path / "upload" / "results.tar.gz"
    inv = _make_upload(
        tmp_path,
        results_url=f"file://{results_dir}",
        results_upload_url=f"file://{dest}",
    )
    await inv._post_run()
    assert dest.exists()
    with tarfile.open(dest, "r:gz") as tar:
        assert tar.getnames() == []


@pytest.mark.asyncio
async def test_post_run_unsupported_upload_scheme(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    inv = _make_upload(
        tmp_path,
        results_url=f"file://{results_dir}",
        results_upload_url="s3://bucket/out.tgz",
    )
    with pytest.raises(ValueError, match="Unsupported scheme"):
        await inv._post_run()


@pytest.mark.asyncio
async def test_post_run_https_upload_integration(
    tmp_path: Path,
    http_server: tuple[str, Path, dict[str, int]],
) -> None:
    url, directory, _ = http_server
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "result.json").write_text('{"ok": true}')

    upload_url = f"{url}/uploaded.tar.gz"
    inv = _make_upload(
        tmp_path,
        results_url=f"file://{results_dir}",
        results_upload_url=upload_url,
    )
    await inv._post_run()

    uploaded = directory / "uploaded.tar.gz"
    assert uploaded.exists()
    with tarfile.open(uploaded, "r:gz") as tar:
        assert "result.json" in tar.getnames()


@pytest.mark.asyncio
async def test_post_run_https_retries_on_5xx(
    tmp_path: Path,
    http_server: tuple[str, Path, dict[str, int]],
) -> None:
    url, directory, fail_state = http_server
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "r.txt").write_text("x")
    fail_state["_fail_remaining"] = 1  # first PUT returns 500

    inv = _make_upload(
        tmp_path,
        results_url=f"file://{results_dir}",
        results_upload_url=f"{url}/out.tar.gz",
    )
    await inv._post_run()
    assert (directory / "out.tar.gz").exists()


@pytest.mark.asyncio
async def test_post_run_upload_4xx_does_not_retry(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "r.txt").write_text("x")

    response = httpx.Response(
        403, request=httpx.Request("PUT", "https://example.com/out")
    )

    class FakeClient:
        call_count = 0

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        async def put(self, *args: Any, **kwargs: Any) -> httpx.Response:
            FakeClient.call_count += 1
            return response

    inv = _make_upload(
        tmp_path,
        results_url=f"file://{results_dir}",
        results_upload_url="https://example.com/out",
    )
    with patch("wt_invokers.mixins.httpx.AsyncClient", FakeClient):
        with pytest.raises(httpx.HTTPStatusError):
            await inv._post_run()
    assert FakeClient.call_count == 1  # no retry on 4xx


@pytest.mark.asyncio
async def test_post_run_cleans_up_temp_tarball_on_error(tmp_path: Path) -> None:
    """Temp tarball is unlinked even when the upload raises."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "r.txt").write_text("x")

    class Boom:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> Boom:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        async def put(self, *args: Any, **kwargs: Any) -> httpx.Response:
            raise httpx.ConnectError("connect refused")

    created: list[str] = []
    real_ntf = mixins.tempfile.NamedTemporaryFile

    def tracking_ntf(*args: Any, **kwargs: Any) -> Any:
        f = real_ntf(*args, **kwargs)
        created.append(f.name)
        return f

    inv = _make_upload(
        tmp_path,
        results_url=f"file://{results_dir}",
        results_upload_url="https://example.com/out",
    )
    with (
        patch("wt_invokers.mixins.httpx.AsyncClient", Boom),
        patch("wt_invokers.mixins.tempfile.NamedTemporaryFile", tracking_ntf),
    ):
        with pytest.raises(httpx.ConnectError):
            await inv._post_run()

    assert created, "temp file should have been created"
    for path in created:
        assert not Path(path).exists(), f"temp file {path} should be cleaned up"


# ---------------------------------------------------------------------------
# RetryableHTTPError — simple smoke test
# ---------------------------------------------------------------------------


def test_retryable_http_error_is_exception() -> None:
    assert issubclass(RetryableHTTPError, Exception)


# ---------------------------------------------------------------------------
# Upload content streams via httpx (no manual read)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_streams_content_with_headers(tmp_path: Path) -> None:
    """Upload streams chunks via an async iterator and sets required headers.

    The archive must not be buffered into memory as a single bytes payload;
    ``_upload_with_retries`` should pass an async iterator to httpx so large
    results archives stream chunk-by-chunk. ``Content-Type`` and
    ``Content-Length`` headers must still be set (GCS signed URLs require
    ``Content-Length``).
    """
    from collections.abc import AsyncIterator

    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "r.txt").write_text("x")

    captured: dict[str, Any] = {}

    class RecordingClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> RecordingClient:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        async def put(
            self, url: str, content: Any = None, headers: Any = None
        ) -> httpx.Response:
            captured["content"] = content
            captured["content_bytes"] = b"".join([chunk async for chunk in content])
            captured["headers"] = headers
            return httpx.Response(200, request=httpx.Request("PUT", url))

    inv = _make_upload(
        tmp_path,
        results_url=f"file://{results_dir}",
        results_upload_url="https://example.com/out",
    )
    with patch("wt_invokers.mixins.httpx.AsyncClient", RecordingClient):
        await inv._post_run()

    assert isinstance(captured["content"], AsyncIterator)
    assert len(captured["content_bytes"]) > 0
    assert captured["headers"]["Content-Type"] == "application/gzip"
    assert "Content-Length" in captured["headers"]
    assert captured["headers"]["Content-Length"] == str(len(captured["content_bytes"]))


# ---------------------------------------------------------------------------
# httpx mock unit tests for download retry accounting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_retries_on_transport_error(tmp_path: Path) -> None:
    calls: dict[str, int] = {"n": 0}

    class FlakyClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FlakyClient:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        def stream(self, method: str, url: str) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectError("refused")

            class _Ok:
                async def __aenter__(self_inner) -> httpx.Response:
                    r = MagicMock()
                    r.status_code = 200
                    r.raise_for_status = MagicMock()

                    async def _iter(chunk_size: int) -> Any:
                        yield b"ok"

                    r.aiter_bytes = _iter
                    return r

                async def __aexit__(self_inner, *exc: Any) -> None:
                    return None

            return _Ok()

    inv = _make_pixi(tmp_path, environment_tar_url="https://example.com/env.tar")
    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        patch("wt_invokers.mixins.httpx.AsyncClient", FlakyClient),
        patch("wt_invokers.mixins.subprocess.run"),
    ):
        await inv._pre_run()
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_download_gives_up_after_max_attempts(tmp_path: Path) -> None:
    calls: dict[str, int] = {"n": 0}

    class AlwaysFail:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> AlwaysFail:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        def stream(self, method: str, url: str) -> Any:
            calls["n"] += 1
            raise httpx.ConnectError("refused")

    inv = _make_pixi(tmp_path, environment_tar_url="https://example.com/env.tar")
    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        patch("wt_invokers.mixins.httpx.AsyncClient", AlwaysFail),
    ):
        with pytest.raises(httpx.ConnectError):
            await inv._pre_run()
    # fast_stamina sets attempts=3
    assert calls["n"] == 3


# suppress unused import warning
_ = AsyncMock

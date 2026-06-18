"""Tests for PixiUnpackMixin and UploadResultsArchiveMixin.

These mixins plug into AbstractInvoker's hook system. They are tested in
isolation by constructing lightweight ad-hoc invokers, populating
``run_args`` and ``run_state`` directly, and invoking ``_pre_run`` /
``_post_run``. A local HTTP server fixture (``http_server``) is used for
integration coverage of the real httpx download/upload path; unit tests
mock httpx for fine-grained retry behaviour.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tarfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
import stamina
from rattler import MatchSpec

from wt_invokers import mixins
from wt_invokers.abstract import AbstractInvoker
from wt_invokers.exceptions import EnvironmentTarDigestError, PixiUnpackError
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

    work_dir: str = ""  # always overridden by _make_pixi via tmp_path

    async def is_installed(self) -> bool:
        return True

    async def install(self) -> None:
        pass

    async def _run(self, **kwargs: Any) -> None:
        pass

    async def _wait(
        self,
        timeout: float | None = None,  # noqa: ASYNC109  # mirrors abstract _wait signature under test
        error_msg: str | None = None,
    ) -> int:
        return 0

    @property
    def is_waitable(self) -> bool:
        return True


@dataclass
class _UploadOnly(UploadResultsArchiveMixin, AbstractInvoker):
    """Minimal invoker composing only UploadResultsArchiveMixin."""

    work_dir: str = ""  # always overridden by _make_upload via tmp_path

    async def is_installed(self) -> bool:
        return True

    async def install(self) -> None:
        pass

    async def _run(self, **kwargs: Any) -> None:
        pass

    async def _wait(
        self,
        timeout: float | None = None,  # noqa: ASYNC109  # mirrors abstract _wait signature under test
        error_msg: str | None = None,
    ) -> int:
        return 0

    @property
    def is_waitable(self) -> bool:
        return True


def _digest(data: bytes) -> str:
    """sha256 of ``data`` in the ``sha256:<hex>`` form the mixin compares against."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


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
    assert mixins.TRANSFER_CHUNK_SIZE == 8 * 1024 * 1024


# ---------------------------------------------------------------------------
# PixiUnpackMixin tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_run_raises_if_pixi_unpack_missing(tmp_path: Path) -> None:
    inv = _make_pixi(tmp_path, environment_tar_url="file:///doesnt-matter")
    with (
        patch("wt_invokers.mixins.shutil.which", return_value=None),
        pytest.raises(RuntimeError, match="pixi-unpack not found"),
    ):
        await inv._pre_run()


@pytest.mark.asyncio
async def test_pre_run_missing_env_url_raises(tmp_path: Path) -> None:
    inv = _make_pixi(tmp_path)
    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        pytest.raises(ValueError, match="environment_tar_url is required"),
    ):
        await inv._pre_run()


@pytest.mark.asyncio
async def test_pre_run_unsupported_scheme(tmp_path: Path) -> None:
    inv = _make_pixi(
        tmp_path,
        environment_tar_url="s3://bucket/env.tar",
        environment_tar_digest=_digest(b"x"),
    )
    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        pytest.raises(ValueError, match="Unsupported scheme"),
    ):
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
        environment_tar_digest=_digest(b"fake-tarball"),
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
    inv = _make_pixi(
        tmp_path,
        environment_tar_url=f"file://{source_tar}",
        environment_tar_digest=_digest(b"bad"),
    )
    underlying = subprocess.CalledProcessError(
        2, "pixi-unpack", output=b"out", stderr=b"err"
    )
    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        patch("wt_invokers.mixins.subprocess.run", side_effect=underlying),
        pytest.raises(PixiUnpackError) as excinfo,
    ):
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
    inv = _make_pixi(
        work,
        environment_tar_url=f"{url}/env.tar",
        environment_tar_digest=_digest(b"streamed-bytes"),
    )

    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        patch("wt_invokers.mixins.subprocess.run") as mock_run,
    ):
        await inv._pre_run()

    assert (work / "environment.tar").read_bytes() == b"streamed-bytes"
    mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_pre_run_follows_redirect(
    tmp_path: Path,
    http_server: tuple[str, Path, dict[str, int]],
) -> None:
    """A 302 redirect (as GitHub release URLs return) is followed."""
    url, directory, _fail = http_server
    (directory / "env.tar").write_bytes(b"redirected-bytes")

    work = tmp_path / "work"
    work.mkdir()
    inv = _make_pixi(
        work,
        environment_tar_url=f"{url}/redirect/env.tar",
        environment_tar_digest=_digest(b"redirected-bytes"),
    )

    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        patch("wt_invokers.mixins.subprocess.run"),
    ):
        await inv._pre_run()

    assert (work / "environment.tar").read_bytes() == b"redirected-bytes"


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
    inv = _make_pixi(
        work,
        environment_tar_url=f"{url}/env.tar",
        environment_tar_digest=_digest(b"bytes-v1"),
    )

    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        patch("wt_invokers.mixins.subprocess.run"),
    ):
        await inv._pre_run()

    assert (work / "environment.tar").read_bytes() == b"bytes-v1"


@pytest.mark.asyncio
async def test_pre_run_download_does_not_retry_on_4xx(tmp_path: Path) -> None:
    """A 4xx response surfaces immediately as HTTPStatusError (no retry)."""
    inv = _make_pixi(
        tmp_path,
        environment_tar_url="https://example.com/env.tar",
        environment_tar_digest=_digest(b"x"),
    )

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
        pytest.raises(httpx.HTTPStatusError),
    ):
        await inv._pre_run()


# ---------------------------------------------------------------------------
# PixiUnpackMixin — environment.tar integrity check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_run_missing_digest_raises(tmp_path: Path) -> None:
    """environment_tar_digest is required -- absence raises before download."""
    source_tar = tmp_path / "env.tar"
    source_tar.write_bytes(b"fake-tarball")
    inv = _make_pixi(tmp_path, environment_tar_url=f"file://{source_tar}")
    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        pytest.raises(ValueError, match="environment_tar_digest is required"),
    ):
        await inv._pre_run()


@pytest.mark.asyncio
async def test_pre_run_digest_mismatch_raises_file(tmp_path: Path) -> None:
    """A wrong digest raises and never runs pixi-unpack (file:// path)."""
    source = tmp_path / "source"
    source.mkdir()
    source_tar = source / "env.tar"
    source_tar.write_bytes(b"fake-tarball")

    work = tmp_path / "work"
    work.mkdir()

    wrong_digest = _digest(b"different-bytes")
    inv = _make_pixi(
        work,
        environment_tar_url=f"file://{source_tar}",
        environment_tar_digest=wrong_digest,
    )

    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        patch("wt_invokers.mixins.subprocess.run") as mock_run,
        pytest.raises(
            EnvironmentTarDigestError,
            match=r"environment\.tar integrity check failed",
        ),
    ):
        await inv._pre_run()

    # The tarball was downloaded, but unpack was skipped and no env activated.
    assert (work / "environment.tar").read_bytes() == b"fake-tarball"
    mock_run.assert_not_called()
    assert "activate_path" not in inv.run_state


@pytest.mark.asyncio
async def test_pre_run_digest_mismatch_raises_http(
    tmp_path: Path,
    http_server: tuple[str, Path, dict[str, int]],
) -> None:
    """A wrong digest raises and never runs pixi-unpack (http path)."""
    url, directory, _fail = http_server
    (directory / "env.tar").write_bytes(b"streamed-bytes")

    work = tmp_path / "work"
    work.mkdir()
    inv = _make_pixi(
        work,
        environment_tar_url=f"{url}/env.tar",
        environment_tar_digest=_digest(b"not-the-bytes"),
    )

    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        patch("wt_invokers.mixins.subprocess.run") as mock_run,
        pytest.raises(
            EnvironmentTarDigestError,
            match=r"environment\.tar integrity check failed",
        ),
    ):
        await inv._pre_run()

    mock_run.assert_not_called()
    assert "activate_path" not in inv.run_state


@pytest.mark.asyncio
async def test_pre_run_digest_match_is_case_insensitive(tmp_path: Path) -> None:
    """An uppercase-hex digest still matches the lowercase computed digest."""
    source_tar = tmp_path / "env.tar"
    source_tar.write_bytes(b"fake-tarball")

    work = tmp_path / "work"
    work.mkdir()
    inv = _make_pixi(
        work,
        environment_tar_url=f"file://{source_tar}",
        environment_tar_digest=_digest(b"fake-tarball").upper(),
    )

    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        patch("wt_invokers.mixins.subprocess.run") as mock_run,
    ):
        await inv._pre_run()

    mock_run.assert_called_once()
    assert inv.run_state["activate_path"] == str(work / "activate.sh")


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    """_sha256_file streams the file and returns the sha256:<hex> form."""
    data = b"some-environment-tarball-bytes" * 1000
    f = tmp_path / "env.tar"
    f.write_bytes(data)
    assert mixins._sha256_file(f) == f"sha256:{hashlib.sha256(data).hexdigest()}"


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
    with (
        patch("wt_invokers.mixins.httpx.AsyncClient", FakeClient),
        pytest.raises(httpx.HTTPStatusError),
    ):
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
        pytest.raises(httpx.ConnectError),
    ):
        await inv._post_run()

    assert created, "temp file should have been created"
    for path in created:
        assert not Path(path).exists(), f"temp file {path} should be cleaned up"  # noqa: ASYNC240  # local FS metadata; fast


# ---------------------------------------------------------------------------
# RetryableHTTPError — simple smoke test
# ---------------------------------------------------------------------------


def test_retryable_http_error_is_exception() -> None:
    assert issubclass(RetryableHTTPError, Exception)


# ---------------------------------------------------------------------------
# archive_results_safely — TarSlip hardening tests
# ---------------------------------------------------------------------------


def _names_in(archive: Path) -> set[str]:
    with tarfile.open(archive, "r:gz") as tar:
        return set(tar.getnames())


def test_archive_results_safely_happy_path(tmp_path: Path) -> None:
    """Regular files and subdirectories archive with their names preserved."""
    results = tmp_path / "results"
    results.mkdir()
    (results / "result.json").write_text('{"ok": true}')
    sub = results / "sub"
    sub.mkdir()
    (sub / "inner.txt").write_text("hi")

    dest = tmp_path / "out.tar.gz"
    mixins.archive_results_safely(results, dest)

    names = _names_in(dest)
    assert "result.json" in names
    assert "sub" in names
    assert "sub/inner.txt" in names


def test_archive_results_safely_empty_dir(tmp_path: Path) -> None:
    """An empty results dir produces a valid (empty) gz-tar."""
    results = tmp_path / "results"
    results.mkdir()
    dest = tmp_path / "out.tar.gz"
    mixins.archive_results_safely(results, dest)

    with tarfile.open(dest, "r:gz") as tar:
        assert tar.getnames() == []


def test_archive_results_safely_rejects_symlink_outside_tree(tmp_path: Path) -> None:
    """Threat: malicious workflow plants ``results/evil -> /etc/passwd``.

    If this entry shipped, a naive ``tar xzf`` on the consumer would follow
    the symlink and expose (or overwrite, if running as root) files outside
    the extraction root — classic TarSlip via absolute symlink. The filter
    must raise rather than silently omit the entry; silent omission would
    let a malicious archive ship "sanitized" without the operator knowing
    the workflow tried something funny.
    """
    results = tmp_path / "results"
    results.mkdir()
    target = tmp_path / "outside"
    target.write_text("secret")
    (results / "evil").symlink_to(target)
    (results / "ok.txt").write_text("ok")

    dest = tmp_path / "out.tar.gz"
    with pytest.raises(tarfile.AbsoluteLinkError):
        mixins.archive_results_safely(results, dest)


def test_archive_results_safely_rejects_fifo(tmp_path: Path) -> None:
    """Threat: workflow smuggles a FIFO into the archive.

    Extraction stalls waiting for a writer, or lands a FIFO on the
    consumer's filesystem that a downstream pipeline might accidentally
    read and hang on. Special-file smuggling — the filter must refuse the
    archive outright.
    """
    if not hasattr(os, "mkfifo"):
        pytest.skip("mkfifo unavailable on this platform")

    results = tmp_path / "results"
    results.mkdir()
    os.mkfifo(results / "pipe")
    (results / "ok.txt").write_text("ok")

    dest = tmp_path / "out.tar.gz"
    with pytest.raises(tarfile.SpecialFileError):
        mixins.archive_results_safely(results, dest)


def test_archive_rejects_relative_symlink_escape(tmp_path: Path) -> None:
    """Threat: same TarSlip class as the absolute-symlink test, but via a
    *relative* target (``../../outside``).

    Different code path inside ``data_filter``: it resolves the link target
    relative to the member's directory and commonpath-checks against the
    destination. This test covers the case where our filter wiring might
    accidentally only catch absolute targets.
    """
    results = tmp_path / "results"
    results.mkdir()
    (results / "evil").symlink_to("../../outside")
    (results / "ok.txt").write_text("ok")

    with pytest.raises(tarfile.FilterError):
        mixins.archive_results_safely(results, tmp_path / "out.tar.gz")


def test_archive_strips_setuid_setgid(tmp_path: Path) -> None:
    """Threat: workflow emits a setuid binary.

    If the archive lands on a system that extracts as root onto a
    filesystem mounted with ``suid``, an unprivileged user could exec it
    for privilege escalation. The filter must strip the high mode bits at
    archive time.
    """
    results = tmp_path / "results"
    results.mkdir()
    f = results / "suid"
    f.write_text("x")
    f.chmod(0o4755)

    dest = tmp_path / "out.tar.gz"
    mixins.archive_results_safely(results, dest)
    with tarfile.open(dest, "r:gz") as tar:
        info = tar.getmember("suid")
        assert info.mode & 0o7000 == 0


def test_archive_normalizes_ownership(tmp_path: Path) -> None:
    """Threat: correctness regression, not an attack.

    ``data_filter`` nulls ``uid`` / ``gid`` / ``uname`` / ``gname`` (for
    extraction); our shim re-sets them to anonymous defaults so the tar
    header writer can serialize them. If the shim is deleted or bypassed,
    archive writing crashes on ``None`` fields — this test catches that
    before release.
    """
    results = tmp_path / "results"
    results.mkdir()
    (results / "f.txt").write_text("x")

    dest = tmp_path / "out.tar.gz"
    mixins.archive_results_safely(results, dest)
    with tarfile.open(dest, "r:gz") as tar:
        for info in tar.getmembers():
            assert info.uid == 0
            assert info.gid == 0
            assert info.uname == ""
            assert info.gname == ""


def test_archive_extracts_safely_into_scratch_dir(tmp_path: Path) -> None:
    """Threat: defense-in-depth proof that the produced archive is actually
    consumer-safe.

    Guards against a future bug where our filter produces structurally-
    malformed entries that a consumer's ``filter="data"`` extraction would
    reject — we'd rather fail our own tests than fail a user's extraction.
    """
    results = tmp_path / "results"
    results.mkdir()
    (results / "result.json").write_text('{"ok": true}')
    (results / "sub").mkdir()
    (results / "sub" / "inner.txt").write_text("hi")
    dest = tmp_path / "out.tar.gz"
    mixins.archive_results_safely(results, dest)

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with tarfile.open(dest, "r:gz") as tar:
        tar.extractall(scratch, filter="data")
    scratch_real = scratch.resolve()
    for p in scratch.rglob("*"):
        resolved = p.resolve()
        assert resolved == scratch_real or scratch_real in resolved.parents


# ---------------------------------------------------------------------------
# _archive_filter — unit tests on synthesized TarInfo
# ---------------------------------------------------------------------------


def test_archive_filter_normalizes_absolute_path_name() -> None:
    """Threat: archive entry whose name is an absolute path.

    A naive consumer treating the name as absolute would write straight to
    ``/etc/passwd``. ``data_filter`` defuses this by stripping the leading
    ``/``, so the entry becomes a safe relative path. Our production
    pipeline can't produce such an entry (we pass ``arcname=item.name``
    from ``iterdir()``, which is always a basename), so this is regression
    coverage — if someone later changes the archive loop to synthesize
    TarInfos directly or accept pre-built entries, this test ensures the
    filter still neutralizes the absolute name.
    """
    info = tarfile.TarInfo(name="/etc/passwd")
    info.type = tarfile.REGTYPE
    out = mixins._archive_filter(info)
    assert not out.name.startswith("/")
    assert out.name == "etc/passwd"


def test_archive_filter_rejects_parent_traversal_name() -> None:
    """Threat: entry name containing ``..`` components.

    Same shape as the absolute-path test — can't happen via the current
    ``iterdir()`` path, but the filter must reject ``..`` components to
    remain a correct backstop for any future code path that builds
    TarInfos directly.
    """
    info = tarfile.TarInfo(name="../escape")
    info.type = tarfile.REGTYPE
    with pytest.raises(tarfile.OutsideDestinationError):
        mixins._archive_filter(info)


@pytest.mark.parametrize("devtype", [tarfile.BLKTYPE, tarfile.CHRTYPE])
def test_archive_filter_rejects_device_node(devtype: bytes) -> None:
    """Threat: device-node entry causes the consumer's extractor to attempt
    ``mknod`` on extraction.

    If the consumer is running as root (or has ``CAP_MKNOD``), they end up
    with a device file on their filesystem that could be used to bypass
    access controls on the underlying block device. Creating real device
    nodes requires root, so this test is only reachable via synthesized
    ``TarInfo``.
    """
    info = tarfile.TarInfo(name="dev")
    info.type = devtype
    with pytest.raises(tarfile.SpecialFileError):
        mixins._archive_filter(info)


def test_archive_filter_rejects_fifo_synthesized() -> None:
    """Threat: same FIFO-smuggling attack as the filesystem-level FIFO
    test, but exercised without ``os.mkfifo``.

    Ensures the filter's FIFO check is covered even on platforms where
    filesystem-level FIFO creation isn't available (e.g. Windows CI
    runners).
    """
    info = tarfile.TarInfo(name="pipe")
    info.type = tarfile.FIFOTYPE
    with pytest.raises(tarfile.SpecialFileError):
        mixins._archive_filter(info)


def test_archive_filter_normalizes_regular_file_fields() -> None:
    """Threat: regression coverage for the normalization shim in isolation.

    If a refactor inlines or deletes the shim, this unit test fails
    directly on the filter's contract, independent of the rest of the
    archive pipeline.
    """
    info = tarfile.TarInfo(name="ok.txt")
    info.type = tarfile.REGTYPE
    info.mode = 0o644
    info.uid = 1000
    info.gid = 1000
    info.uname = "alice"
    info.gname = "alice"

    out = mixins._archive_filter(info)
    assert out.uid == 0
    assert out.gid == 0
    assert out.uname == ""
    assert out.gname == ""
    assert out.mode is not None


# ---------------------------------------------------------------------------
# file:// URL path percent-decoding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_run_file_url_with_space_in_path(tmp_path: Path) -> None:
    """file:// URLs with percent-encoded spaces round-trip through url2pathname."""
    source = tmp_path / "src with space"
    source.mkdir()
    source_tar = source / "env.tar"
    source_tar.write_bytes(b"bytes")

    work = tmp_path / "work dir"
    work.mkdir()

    # urlparse("file:///tmp/src%20with%20space/env.tar").path keeps the
    # percent-encoded form; without url2pathname, shutil.copy2 would fail.
    url = f"file://{str(source_tar).replace(' ', '%20')}"
    inv = _make_pixi(
        work,
        environment_tar_url=url,
        environment_tar_digest=_digest(b"bytes"),
    )

    with (
        patch("wt_invokers.mixins.shutil.which", return_value="/usr/bin/pixi-unpack"),
        patch("wt_invokers.mixins.subprocess.run"),
    ):
        await inv._pre_run()

    assert (work / "environment.tar").read_bytes() == b"bytes"


@pytest.mark.asyncio
async def test_post_run_file_urls_with_space_in_path(tmp_path: Path) -> None:
    """file:// URLs for results dir and upload dest handle percent-encoded paths."""
    results_dir = tmp_path / "res dir"
    results_dir.mkdir()
    (results_dir / "result.json").write_text("{}")

    dest = tmp_path / "up load" / "out.tar.gz"
    results_url = f"file://{str(results_dir).replace(' ', '%20')}"
    upload_url = f"file://{str(dest).replace(' ', '%20')}"

    inv = _make_upload(
        tmp_path,
        results_url=results_url,
        results_upload_url=upload_url,
    )
    await inv._post_run()

    assert dest.exists()


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
# Module-level transfer helpers — retry accounting
#
# `_download_with_retries` / `_upload_with_retries` are module-level helpers
# (not bound methods on the mixins), so we test the retry behaviour by
# calling them directly rather than going through `_pre_run` scaffolding.
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
                async def __aenter__(self) -> httpx.Response:
                    r = MagicMock()
                    r.status_code = 200
                    r.raise_for_status = MagicMock()

                    async def _iter(chunk_size: int) -> Any:
                        yield b"ok"

                    r.aiter_bytes = _iter
                    return r

                async def __aexit__(self, *exc: Any) -> None:
                    return None

            return _Ok()

    dest = tmp_path / "env.tar"
    with patch("wt_invokers.mixins.httpx.AsyncClient", FlakyClient):
        await mixins._download_with_retries("https://example.com/env.tar", dest)
    assert calls["n"] == 2
    assert dest.read_bytes() == b"ok"


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

    dest = tmp_path / "env.tar"
    with (
        patch("wt_invokers.mixins.httpx.AsyncClient", AlwaysFail),
        pytest.raises(httpx.ConnectError),
    ):
        await mixins._download_with_retries("https://example.com/env.tar", dest)
    # fast_stamina sets attempts=3
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_upload_retries_on_transport_error(tmp_path: Path) -> None:
    """Symmetric retry coverage for the upload helper."""
    payload = tmp_path / "archive.tar.gz"
    payload.write_bytes(b"payload")
    calls: dict[str, int] = {"n": 0}

    class FlakyClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FlakyClient:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        async def put(self, url: str, **kwargs: Any) -> httpx.Response:
            # Drain the streaming body so the client behaves like a real one.
            async for _ in kwargs["content"]:
                pass
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectError("refused")
            return httpx.Response(200, request=httpx.Request("PUT", url))

    with patch("wt_invokers.mixins.httpx.AsyncClient", FlakyClient):
        await mixins._upload_with_retries(payload, "https://example.com/out")
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_upload_gives_up_after_max_attempts(tmp_path: Path) -> None:
    payload = tmp_path / "archive.tar.gz"
    payload.write_bytes(b"payload")
    calls: dict[str, int] = {"n": 0}

    class AlwaysFail:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> AlwaysFail:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        async def put(self, url: str, **kwargs: Any) -> httpx.Response:
            calls["n"] += 1
            raise httpx.ConnectError("refused")

    with (
        patch("wt_invokers.mixins.httpx.AsyncClient", AlwaysFail),
        pytest.raises(httpx.ConnectError),
    ):
        await mixins._upload_with_retries(payload, "https://example.com/out")
    # fast_stamina sets attempts=3
    assert calls["n"] == 3

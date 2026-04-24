"""Pre/post-run mixins for invokers.

This module defines mixins that hook into :class:`AbstractInvoker`'s
``_pre_run`` / ``_post_run`` lifecycle methods. Mixins are composed in MRO
order on concrete invokers (see :class:`wt_invokers.sandbox.SandboxInvoker`).

Two mixins are provided:

* :class:`PixiUnpackMixin` — downloads a pixi-pack environment tarball from a
  URL and unpacks it before the workflow runs.
* :class:`UploadResultsArchiveMixin` — tars the results directory after the
  workflow finishes and uploads the archive to a signed URL.

Both mixins share a common HTTP transfer configuration (retry policy,
timeouts, chunk size) via module-level constants that can be overridden via
environment variables.

Composition convention
----------------------
Hooks MUST call ``await super()._pre_run()`` / ``await super()._post_run()``
as their first line so multi-mixin composition works correctly: the base
:class:`AbstractInvoker` hooks are no-ops, but if a future mixin is inserted
into the MRO ahead of the base class, skipping the ``super()`` call would
silently drop its hook.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
from urllib.request import url2pathname

import httpx
import stamina

from .exceptions import PixiUnpackError

# ---------------------------------------------------------------------------
# Shared HTTP transfer configuration
# ---------------------------------------------------------------------------
# Override via environment variables. These govern both download
# (PixiUnpackMixin) and upload (UploadResultsArchiveMixin).

TRANSFER_MAX_ATTEMPTS = int(os.environ.get("WT_INVOKERS__TRANSFER_MAX_ATTEMPTS", "5"))
TRANSFER_RETRY_WAIT_INITIAL = float(
    os.environ.get("WT_INVOKERS__TRANSFER_RETRY_WAIT_INITIAL", "1.0")
)
TRANSFER_RETRY_WAIT_MAX = float(
    os.environ.get("WT_INVOKERS__TRANSFER_RETRY_WAIT_MAX", "60.0")
)
TRANSFER_CONNECT_TIMEOUT = float(
    os.environ.get("WT_INVOKERS__TRANSFER_CONNECT_TIMEOUT", "30.0")
)
TRANSFER_TIMEOUT = float(os.environ.get("WT_INVOKERS__TRANSFER_TIMEOUT", "1800.0"))
# Default chosen for the 100 MB – 2 GB typical transfer range against cloud
# object storage. 8 MiB keeps syscall overhead negligible (~128 reads/GB) and
# comfortably covers the GCP inter-region bandwidth-delay-product so TCP
# doesn't stall on app-layer drain lag.
TRANSFER_CHUNK_SIZE = int(
    os.environ.get("WT_INVOKERS__TRANSFER_CHUNK_SIZE", str(8 * 1024 * 1024))
)


class RetryableHTTPError(Exception):
    """Raised on 5xx HTTP errors to trigger stamina retry."""


def _timeout() -> httpx.Timeout:
    return httpx.Timeout(
        connect=TRANSFER_CONNECT_TIMEOUT,
        read=TRANSFER_TIMEOUT,
        write=TRANSFER_TIMEOUT,
        pool=TRANSFER_CONNECT_TIMEOUT,
    )


# ---------------------------------------------------------------------------
# Safe archive helper (producer-side TarSlip hardening)
# ---------------------------------------------------------------------------


def archive_results_safely(results_dir: Path, dest: Path) -> None:
    """Write a gzip-tar of ``results_dir`` to ``dest`` with TarSlip hardening.

    Threat model (producer side)
    ----------------------------
    This function is the final step before a results archive leaves the
    sandbox container. The workflow that produced ``results_dir`` is
    untrusted — it runs inside the sandbox and may write arbitrary entries
    into ``results_dir``, including entries that would be unsafe for a
    downstream consumer to extract (symlinks pointing at system paths,
    hardlinks, absolute-path members, path-traversal via ``..``, device
    files, setuid/setgid bits). A consumer extracting the archive without
    a filter (the pre-3.12 default) would suffer arbitrary writes on its
    own filesystem — a pivot from the sandbox to the consumer.

    What this defends against
    -------------------------
    Applies :func:`tarfile.data_filter` at archive time. That filter rejects
    entries with absolute paths, ``..`` components, symlinks/hardlinks with
    external targets, device files, FIFOs, and setuid/setgid bits. The
    produced archive is safe for any downstream consumer, including those on
    Python < 3.12 or those using non-Python extractors with old defaults.

    What this does NOT defend against
    ---------------------------------
    Data exfiltration. The workflow can copy any readable file into
    ``results_dir`` as a regular file (e.g. ``shutil.copy("/etc/passwd",
    results_dir / "passwd")``). Regular-file entries are not filtered because
    they are indistinguishable from legitimate workflow output. Defenses
    against exfiltration are architectural: container filesystem hardening,
    service-account scoping on the Cloud Run Job, egress policy, and the fact
    that ``results_upload_url`` is an orchestrator-controlled signed URL
    constraining where the archive can land. Those live outside this function.

    Consumer guidance
    -----------------
    Even though this producer is hardened, consumers SHOULD still extract
    with ``tarfile.extractall(filter="data")`` as defense-in-depth — this
    producer cannot guarantee the archive they receive came from a hardened
    producer (e.g. a user-supplied archive from a different source), so
    filtering at extract time is the consumer's own hygiene.
    """

    def _reject_unsafe(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
        # ``tarfile.data_filter`` is designed for extraction, but its checks
        # (no absolute paths / ``..`` / links escaping the tree / device
        # files / FIFOs / setuid-setgid) are exactly what we want to apply
        # at archive time too. Run them, catching the FilterError class it
        # raises on any unsafe member; return ``None`` to exclude rejected
        # entries from the archive.
        #
        # ``data_filter`` intentionally nulls some fields (uid / gid /
        # uname / gname / sometimes mode) because those are meant to be
        # recomputed at extraction time. But the archive header serializer
        # cannot write ``None`` values, so we harmonize to safe anonymous
        # defaults before handing the TarInfo back to ``add``.
        try:
            filtered = tarfile.data_filter(tarinfo, "")
        except tarfile.FilterError:
            return None
        # mypy knows ``mode`` is typed as ``int`` but data_filter sets it
        # to ``None`` for some member types; cast-via-getattr keeps the
        # runtime safety without tripping the unreachable-branch warning.
        if getattr(filtered, "mode", None) is None:
            filtered.mode = 0o755 if tarinfo.isdir() else 0o644
        filtered.uid = 0
        filtered.gid = 0
        filtered.uname = ""
        filtered.gname = ""
        return filtered

    with tarfile.open(dest, "w:gz") as tar:
        for item in results_dir.iterdir():
            tar.add(item, arcname=item.name, filter=_reject_unsafe)


# ---------------------------------------------------------------------------
# PixiUnpackMixin
# ---------------------------------------------------------------------------


class PixiUnpackMixin:
    """Pre-run hook that downloads and unpacks a pixi-pack environment tarball.

    Reads ``environment_tar_url`` from :attr:`~AbstractInvoker.run_args`,
    writes the downloaded tarball to ``{work_dir}/environment.tar``, invokes
    ``pixi-unpack`` on it, and records the path to the activation script in
    :attr:`~AbstractInvoker.run_state` under the key ``"activate_path"`` so
    downstream ``_run`` implementations can source it.

    Supports ``file://``, ``http://``, and ``https://`` URL schemes for the
    tarball source. HTTP(S) downloads are retried via ``stamina`` on transport
    errors and 5xx responses.
    """

    # These attributes come from :class:`AbstractInvoker` at runtime; declared
    # here for the type checker only (no runtime class-dict pollution).
    if TYPE_CHECKING:
        run_args: MappingProxyType[str, Any]
        run_state: dict[str, Any]
        work_dir: str

    async def _pre_run(self) -> None:
        await super()._pre_run()  # type: ignore[misc]
        if shutil.which("pixi-unpack") is None:
            raise RuntimeError(
                "pixi-unpack not found. Install via conda "
                "(included in the wt-invokers conda package) or manually "
                "from https://github.com/Quantco/pixi-pack"
            )

        environment_tar_url = self.run_args.get("environment_tar_url")
        if not environment_tar_url:
            raise ValueError(
                "environment_tar_url is required -- pass it as a kwarg to run()"
            )

        Path(self.work_dir).mkdir(parents=True, exist_ok=True)
        tar_path = Path(self.work_dir) / "environment.tar"

        parsed = urlparse(environment_tar_url)
        if parsed.scheme == "file":
            shutil.copy2(url2pathname(parsed.path), tar_path)
        elif parsed.scheme in ("http", "https"):
            await self._download_with_retries(environment_tar_url, tar_path)
        else:
            raise ValueError(
                f"Unsupported scheme for environment_tar_url: {parsed.scheme}"
            )

        try:
            subprocess.run(
                ["pixi-unpack", str(tar_path)],
                cwd=self.work_dir,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            raise PixiUnpackError(
                f"pixi-unpack failed with exit code {e.returncode}",
                returncode=e.returncode,
                stdout=e.stdout,
                stderr=e.stderr,
            ) from e

        self.run_state["activate_path"] = str(Path(self.work_dir) / "activate.sh")

    async def _download_with_retries(self, url: str, dest: Path) -> None:
        """Download ``url`` to ``dest`` with retries on transient failure."""

        @stamina.retry(
            on=(httpx.TransportError, RetryableHTTPError),
            attempts=TRANSFER_MAX_ATTEMPTS,
            wait_initial=TRANSFER_RETRY_WAIT_INITIAL,
            wait_max=TRANSFER_RETRY_WAIT_MAX,
        )
        async def _do_download() -> None:
            async with (
                httpx.AsyncClient(timeout=_timeout()) as client,
                client.stream("GET", url) as response,
            ):
                if 500 <= response.status_code < 600:
                    raise RetryableHTTPError(
                        f"Server error {response.status_code} downloading {url}"
                    )
                response.raise_for_status()
                with open(dest, "wb") as f:
                    async for chunk in response.aiter_bytes(
                        chunk_size=TRANSFER_CHUNK_SIZE
                    ):
                        # Offload blocking file I/O so the event loop stays
                        # responsive (matters if a concurrent driver ever
                        # shares the loop with the download).
                        await asyncio.to_thread(f.write, chunk)

        await _do_download()


# ---------------------------------------------------------------------------
# UploadResultsArchiveMixin
# ---------------------------------------------------------------------------


class UploadResultsArchiveMixin:
    """Post-run hook that tars the results directory and uploads the archive.

    Reads ``results_url`` (a ``file://`` URL identifying the local results
    directory written by the workflow) and ``results_upload_url`` (the
    destination for the tarball) from :attr:`~AbstractInvoker.run_args`.
    Supports ``file://`` destinations for local testing as well as ``http://``
    / ``https://`` signed-URL uploads via ``PUT`` (used for GCS signed URLs).

    This hook runs even when the workflow exited non-zero so that a
    ``result.json`` describing the failure is still uploaded.

    Security note: this mixin carries untrusted-workflow output out of the
    sandbox. The archive stage is hardened against TarSlip via
    :func:`archive_results_safely`; exfiltration of readable files is a
    separate architectural concern (see the container / IAM / egress policy
    of the deployment).
    """

    # See :class:`PixiUnpackMixin` — typing shim only, no runtime effect.
    if TYPE_CHECKING:
        run_args: MappingProxyType[str, Any]
        run_state: dict[str, Any]
        work_dir: str

    async def _post_run(self) -> None:
        await super()._post_run()  # type: ignore[misc]
        results_url = self.run_args.get("results_url")
        if not results_url:
            raise ValueError("results_url is required -- pass it as an arg to run()")
        results_upload_url = self.run_args.get("results_upload_url")
        if not results_upload_url:
            raise ValueError(
                "results_upload_url is required -- pass it as a kwarg to run()"
            )

        parsed = urlparse(results_url)
        if parsed.scheme not in ("file", ""):
            raise ValueError(
                f"results_url must be a file:// URL for sandbox invoker, "
                f"got: {results_url}"
            )
        results_dir = Path(url2pathname(parsed.path))
        if not results_dir.exists():
            raise RuntimeError(f"Results directory does not exist: {results_dir}")

        # NamedTemporaryFile creates and opens the file; we only need the path,
        # so close the handle and unlink in the finally block below.
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tar_file:
            tar_path = Path(tar_file.name)
        try:
            archive_results_safely(results_dir, tar_path)

            upload_parsed = urlparse(results_upload_url)
            if upload_parsed.scheme == "file":
                dest = Path(url2pathname(upload_parsed.path))
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(tar_path, dest)
            elif upload_parsed.scheme in ("http", "https"):
                await self._upload_with_retries(tar_path, results_upload_url)
            else:
                raise ValueError(
                    f"Unsupported scheme for results_upload_url: {upload_parsed.scheme}"
                )
        finally:
            tar_path.unlink(missing_ok=True)

    async def _upload_with_retries(self, tar_path: Path, url: str) -> None:
        """Upload ``tar_path`` to ``url`` via ``PUT`` with retries.

        Streams the file in ``TRANSFER_CHUNK_SIZE`` chunks rather than reading
        the whole archive into memory. The upload includes an explicit
        ``Content-Length`` header (required by GCS signed-URL uploads) sourced
        from the file's stat size, so the server can validate the request
        without the chunked ``Transfer-Encoding`` fallback.
        """

        size = tar_path.stat().st_size

        @stamina.retry(
            on=(httpx.TransportError, RetryableHTTPError),
            attempts=TRANSFER_MAX_ATTEMPTS,
            wait_initial=TRANSFER_RETRY_WAIT_INITIAL,
            wait_max=TRANSFER_RETRY_WAIT_MAX,
        )
        async def _do_upload() -> None:
            async def _chunks() -> AsyncIterator[bytes]:
                with open(tar_path, "rb") as f:
                    while True:
                        # Offload the blocking read so the event loop can
                        # service other tasks while we wait on disk.
                        chunk = await asyncio.to_thread(f.read, TRANSFER_CHUNK_SIZE)
                        if not chunk:
                            break
                        yield chunk

            async with httpx.AsyncClient(timeout=_timeout()) as client:
                response = await client.put(
                    url,
                    content=_chunks(),
                    headers={
                        "Content-Type": "application/gzip",
                        "Content-Length": str(size),
                    },
                )
                if 500 <= response.status_code < 600:
                    raise RetryableHTTPError(
                        f"Server error {response.status_code} uploading to {url}"
                    )
                response.raise_for_status()

        await _do_upload()

"""Scheme-agnostic byte storage for the cache.

Mirrors how the generated CLI already locates the results store — a URL that may
be a local path or an object-store location. Local paths go through stdlib so
that core `wt-task` keeps its dependencies; anything else needs the `cache`
extra (`obstore`), which every compiled workflow already has.
"""

from __future__ import annotations

import os
import tempfile
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlparse
from urllib.request import url2pathname

from ._settings import ENV_PREFIX, active_settings

if TYPE_CHECKING:
    from typing import Any


class Store(Protocol):
    """A flat key-to-bytes store. Keys are relative, '/'-separated paths."""

    def get(self, key: str) -> bytes | None:
        """Return the stored bytes, or None if the key is absent or empty."""
        ...

    def put(self, key: str, data: bytes) -> None:
        """Store `data` at `key`, atomically with respect to concurrent readers."""
        ...


class LocalStore:
    """Filesystem-backed store rooted at a directory.

    Writes land in a sibling temp file and are renamed into place, so a reader
    never observes a half-written payload. Reads treat a zero-byte file as a
    miss, matching `serde._read_path_if_file_exists` — a truncated write should
    cost a recompute, not serve empty data.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root.joinpath(*key.split("/"))

    def get(self, key: str) -> bytes | None:
        """Return the stored bytes, or None if the key is absent or empty."""
        path = self._path(key)
        if not path.is_file() or path.stat().st_size == 0:
            return None
        return path.read_bytes()

    def put(self, key: str, data: bytes) -> None:
        """Write `data` to `key` via a temp file renamed into place."""
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            # Atomic on POSIX; on Windows replace() also overwrites an existing target.
            Path(tmp).replace(path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


class ObstoreStore:
    """Object-store-backed store. A single PUT is already atomic, so no rename."""

    def __init__(self, store: Any) -> None:  # noqa: ANN401  # obstore is an optional import
        self._store = store

    def get(self, key: str) -> bytes | None:
        """Return the stored bytes, or None if the key is absent or empty."""
        try:
            data = bytes(self._store.get(key).bytes())
        except Exception:  # noqa: BLE001  # obstore raises backend-specific not-found errors
            return None
        return data or None

    def put(self, key: str, data: bytes) -> None:
        """Store `data` at `key`."""
        self._store.put(key, data)


def _local_root(url: str) -> Path | None:
    """Return the local directory `url` names, or None if it is not a local path."""
    parsed = urlparse(url)
    if parsed.scheme == "file":
        return Path(url2pathname(parsed.path))
    if not parsed.scheme or len(parsed.scheme) == 1:  # bare path, or a Windows drive letter
        return Path(url)
    return None


def open_store(url: str | None = None) -> Store | None:
    """Open the cache store, or return None when caching is unavailable.

    Returning None rather than raising is what makes emitted `.cached()` inert:
    with no store configured — or `obstore` missing for a remote URL — every
    step simply runs.

    Args:
        url: Store location. Defaults to this run's `store` setting.

    Examples:
        >>> open_store("") is None
        True
    """
    url = url if url is not None else active_settings().store
    if not url:
        return None

    root = _local_root(url)
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
        return LocalStore(root)

    try:
        import obstore  # noqa: PLC0415  # optional dependency, only needed for remote URLs
    except ImportError:
        warnings.warn(
            f"{ENV_PREFIX}STORE={url!r} needs the `obstore` package; "
            f"install `wt-task[cache]` to enable caching. Running uncached.",
            stacklevel=2,
        )
        return None
    return ObstoreStore(obstore.store.from_url(url))

"""Shared pytest fixtures for wt-invokers tests."""

from __future__ import annotations

import http.server
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


class _UploadHandler(http.server.SimpleHTTPRequestHandler):
    """Handler that accepts PUT (upload) and serves GETs from directory.

    Supports an optional failure counter so tests can simulate transient 5xx
    errors before succeeding.
    """

    # set by the fixture factory
    _fail_remaining: dict[str, int] = {}

    def log_message(self, format: str, *args: Any) -> None:
        return  # silence

    def do_PUT(self) -> None:
        # Simulate transient server failure on first N requests if configured.
        fail_key = "_fail_remaining"
        if self._fail_remaining.get(fail_key, 0) > 0:
            self._fail_remaining[fail_key] -= 1
            self.send_response(500)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length) if length > 0 else b""
        directory = Path(self.directory)  # type: ignore[attr-defined]
        dest = directory / self.path.lstrip("/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        self.send_response(200)
        self.end_headers()

    def do_GET(self) -> None:
        fail_key = "_fail_remaining"
        if self._fail_remaining.get(fail_key, 0) > 0:
            self._fail_remaining[fail_key] -= 1
            self.send_response(500)
            self.end_headers()
            return None
        return super().do_GET()


@pytest.fixture
def http_server(tmp_path: Path) -> Iterator[tuple[str, Path, dict[str, int]]]:
    """Start a local HTTP server for integration tests.

    Yields ``(url, directory, fail_state)`` where ``fail_state`` is a
    mutable dict; setting ``fail_state["_fail_remaining"]`` to N makes the
    next N requests return 500 (useful for retry tests).
    """
    fail_state: dict[str, int] = {}

    def handler_factory(*args: Any, **kwargs: Any) -> _UploadHandler:
        h = _UploadHandler(*args, directory=str(tmp_path), **kwargs)
        return h

    # Monkey-patch per-instance state via class attr (single-server test scope).
    _UploadHandler._fail_remaining = fail_state

    server = http.server.HTTPServer(("127.0.0.1", 0), handler_factory)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", tmp_path, fail_state
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def stamina_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """Speed up stamina retries in tests by disabling the backoff."""
    import stamina

    stamina.set_testing(True, attempts=5)

"""Animated progress spinner for compilation phases.

Provides a threaded spinner that writes status messages to stderr,
auto-disabling when stderr is not a TTY (piped output, CI).

During spinner operation, stderr from child processes and native libraries
(e.g. py-rattler) is captured at the file-descriptor level and displayed
after the spinner completes.
"""
# ruff: noqa: D105, D107  # __init__/__enter__/__exit__/__bool__ are documented at the class level

from __future__ import annotations

import io
import os
import sys
import threading
from typing import IO, TextIO


class _StderrCapture:
    """Low-level file-descriptor redirect of fd 2 into a pipe.

    Captures all stderr output — including from native Rust/C libraries that
    write directly to fd 2 — by redirecting the file descriptor to a pipe and
    draining it in a background thread.

    The caller gets ``terminal_file`` (a Python file wrapping the saved fd)
    to write spinner animation to the real terminal while fd 2 is redirected.

    Args:
        None

    Examples:
        >>> capture = _StderrCapture()  # doctest: +SKIP
        >>> capture.start()  # doctest: +SKIP
        >>> # ... native code writes to fd 2 ...
        >>> text = capture.stop()  # doctest: +SKIP
        >>> capture.close_terminal_file()  # doctest: +SKIP
    """

    def __init__(self) -> None:
        self._saved_fd: int = -1
        self._pipe_r: int = -1
        self._terminal_file: IO[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._captured: bytearray = bytearray()

    @property
    def terminal_file(self) -> IO[str]:
        """Python file object wrapping the real terminal stderr fd."""
        if self._terminal_file is None:
            raise RuntimeError("_StderrCapture has not been started")
        return self._terminal_file

    def start(self) -> None:
        """Begin fd-level stderr capture.

        Raises:
            OSError: If file descriptor operations fail.
        """
        sys.stderr.flush()

        # Save the real fd 2
        self._saved_fd = os.dup(2)

        # Create pipe
        self._pipe_r, pipe_w = os.pipe()

        # Redirect fd 2 to write end of pipe
        os.dup2(pipe_w, 2)
        os.close(pipe_w)  # fd 2 is now the only write-end copy

        # Wrap saved fd as Python file for spinner output
        self._terminal_file = os.fdopen(self._saved_fd, "w")

        # Start reader thread to drain pipe into buffer
        self._captured = bytearray()
        self._reader_thread = threading.Thread(target=self._drain_pipe, daemon=True)
        self._reader_thread.start()

    def stop(self) -> str:
        """Restore fd 2, join reader, return captured text.

        Returns:
            Captured stderr content decoded as UTF-8 (lossy).
        """
        if self._terminal_file is None:
            return ""

        # Flush Python stderr (which currently goes to the pipe)
        sys.stderr.flush()

        # Restore fd 2 to the real terminal.
        # This implicitly closes the old fd 2 (pipe write end),
        # signaling EOF to the reader thread.
        os.dup2(self._terminal_file.fileno(), 2)

        # Wait for reader to finish draining
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=5.0)

        # Close read end of pipe
        if self._pipe_r >= 0:
            os.close(self._pipe_r)
            self._pipe_r = -1

        return self._captured.decode("utf-8", errors="replace")

    def close_terminal_file(self) -> None:
        """Close the terminal file object (releases saved fd)."""
        if self._terminal_file is not None:
            self._terminal_file.close()
            self._terminal_file = None

    def _drain_pipe(self) -> None:
        """Read from pipe until EOF, appending to buffer."""
        while True:
            try:
                chunk = os.read(self._pipe_r, 4096)
            except OSError:
                break
            if not chunk:
                break
            self._captured.extend(chunk)


class Spinner:
    """Animated status spinner for stderr.

    Displays a spinning animation with a status message, updating in-place.
    Designed to be used as a context manager.

    When ``capture_stderr`` is True (the default) and the output file is the
    real stderr (fd 2), all stderr from child processes and native libraries
    is captured at the fd level and printed after the spinner exits.

    Args:
        message: Initial status message to display
        file: Output stream (default: sys.stderr)
        interval: Seconds between frame updates (default: 0.08)
        capture_stderr: Whether to capture fd-level stderr (default: True)

    Examples:
        >>> with Spinner("Loading...") as sp:  # doctest: +SKIP
        ...     sp.update("Phase 1...")
        ...     sp.update("Phase 2...")
    """

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(
        self,
        message: str = "",
        file: IO[str] | TextIO = sys.stderr,
        interval: float = 0.08,
        capture_stderr: bool = True,
    ) -> None:
        self._message = message
        self._file = file
        self._interval = interval
        self._capture_stderr = capture_stderr
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._capture: _StderrCapture | None = None

    def __enter__(self) -> Spinner:
        self._stop_event.clear()

        # Attempt fd-level stderr capture
        if self._capture_stderr and self._is_real_stderr():
            try:
                self._capture = _StderrCapture()
                self._capture.start()
                self._file = self._capture.terminal_file
            except (OSError, io.UnsupportedOperation, AttributeError):
                self._capture = None

        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        # Stop spinner animation
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()

        if self._capture is not None:
            # Restore fd 2 and collect captured output
            captured = self._capture.stop()

            # Clear spinner line on terminal
            self._file.write("\r\033[K")
            self._file.flush()

            # Print captured stderr if any
            if captured.strip():
                self._file.write(captured)
                if not captured.endswith("\n"):
                    self._file.write("\n")
                self._file.flush()

            # Close terminal file (releases saved fd)
            self._capture.close_terminal_file()
            self._capture = None
        else:
            # No capture — original behavior
            self._file.write("\r\033[K")
            self._file.flush()

    def update(self, message: str) -> None:
        """Change the displayed status message.

        Args:
            message: New status message
        """
        with self._lock:
            self._message = message

    def _is_real_stderr(self) -> bool:
        """Check if self._file is the actual stderr fd 2."""
        try:
            return self._file.fileno() == 2
        except (io.UnsupportedOperation, AttributeError, OSError):
            return False

    def _spin(self) -> None:
        """Animation loop running in a background thread."""
        idx = 0
        while not self._stop_event.is_set():
            frame = self.FRAMES[idx % len(self.FRAMES)]
            with self._lock:
                text = self._message
            self._file.write(f"\r\033[K{frame} {text}")
            self._file.flush()
            idx += 1
            self._stop_event.wait(self._interval)


class NullSpinner:
    """No-op spinner with the same interface as Spinner.

    Used when progress display is disabled or stderr is not a TTY.

    Examples:
        >>> with NullSpinner() as sp:
        ...     sp.update("ignored")
    """

    def __enter__(self) -> NullSpinner:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def update(self, message: str) -> None:
        """No-op update.

        Args:
            message: Ignored
        """


def spinner(enabled: bool = True) -> Spinner | NullSpinner:
    """Return a Spinner if enabled and stderr is a TTY, else NullSpinner.

    Args:
        enabled: Whether progress display is requested (default: True)

    Returns:
        Spinner if enabled and stderr is a TTY, otherwise NullSpinner

    Examples:
        >>> sp = spinner(enabled=False)
        >>> isinstance(sp, NullSpinner)
        True
    """
    if enabled and hasattr(sys.stderr, "isatty") and sys.stderr.isatty():
        return Spinner()
    return NullSpinner()

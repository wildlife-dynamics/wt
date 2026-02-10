"""Animated progress spinner for compilation phases.

Provides a threaded spinner that writes status messages to stderr,
auto-disabling when stderr is not a TTY (piped output, CI).
"""

from __future__ import annotations

import sys
import threading
from typing import IO, TextIO


class Spinner:
    """Animated status spinner for stderr.

    Displays a spinning animation with a status message, updating in-place.
    Designed to be used as a context manager.

    Args:
        message: Initial status message to display
        file: Output stream (default: sys.stderr)
        interval: Seconds between frame updates (default: 0.08)

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
    ) -> None:
        self._message = message
        self._file = file
        self._interval = interval
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> Spinner:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
        # Clear the spinner line
        self._file.write("\r\033[K")
        self._file.flush()

    def update(self, message: str) -> None:
        """Change the displayed status message.

        Args:
            message: New status message
        """
        with self._lock:
            self._message = message

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

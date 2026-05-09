"""Exceptions for wt-invokers package.

This module defines custom exceptions used throughout the wt-invokers package.
"""

from __future__ import annotations


class InvokerError(Exception):
    """Base exception for all invoker-related errors.

    Examples:
        Raising a generic invoker error:

        >>> raise InvokerError("Something went wrong")
        Traceback (most recent call last):
            ...
        wt_invokers.exceptions.InvokerError: Something went wrong
    """


class InvocationTimeoutError(InvokerError):
    """Exception raised when a workflow invocation times out.

    This exception is raised when a workflow execution exceeds the specified
    timeout duration.

    Examples:
        Raising a timeout error:

        >>> raise InvocationTimeoutError("Workflow exceeded 300s timeout")
        Traceback (most recent call last):
            ...
        wt_invokers.exceptions.InvocationTimeoutError: Workflow exceeded 300s timeout
    """


class InstallationError(InvokerError):
    """Exception raised when workflow installation fails.

    This exception is raised when a workflow cannot be installed in the
    target environment.

    Examples:
        Raising an installation error:

        >>> raise InstallationError("Failed to install my-workflow>=1.0.0")
        Traceback (most recent call last):
            ...
        wt_invokers.exceptions.InstallationError: Failed to install my-workflow>=1.0.0
    """


class PixiUnpackError(InvokerError):
    """Exception raised when the ``pixi-unpack`` subprocess fails.

    Wraps :class:`subprocess.CalledProcessError` so callers can handle a
    domain-specific exception while still inspecting the captured output
    from the failed ``pixi-unpack`` invocation.

    Attributes:
        returncode: Exit code returned by ``pixi-unpack``.
        stdout: Captured standard output (bytes or str, depending on how
            ``subprocess.run`` was invoked).
        stderr: Captured standard error.

    Examples:
        Raising with captured output:

        >>> err = PixiUnpackError(
        ...     "pixi-unpack failed", returncode=2, stdout=b"", stderr=b"boom"
        ... )
        >>> err.returncode
        2
        >>> err.stderr
        b'boom'
    """

    def __init__(
        self,
        message: str,
        *,
        returncode: int,
        stdout: bytes | str | None,
        stderr: bytes | str | None,
    ) -> None:
        """Initialise with stdout/stderr captured from the failed pixi-unpack call."""
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

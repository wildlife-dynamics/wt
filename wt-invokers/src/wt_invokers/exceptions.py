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

    pass


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

    pass


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

    pass

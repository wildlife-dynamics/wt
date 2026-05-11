"""Tests for exception classes.

This module tests the custom exception hierarchy in wt-invokers.
"""

from __future__ import annotations

import pytest

from wt_invokers.exceptions import (
    InstallationError,
    InvocationTimeoutError,
    InvokerError,
)


def test_invoker_error_is_exception() -> None:
    """Test InvokerError is an Exception."""
    error = InvokerError("Test error")
    assert isinstance(error, Exception)
    assert str(error) == "Test error"


def test_invocation_timeout_error_is_invoker_error() -> None:
    """Test InvocationTimeoutError inherits from InvokerError."""
    error = InvocationTimeoutError("Timeout occurred")
    assert isinstance(error, InvokerError)
    assert isinstance(error, Exception)
    assert str(error) == "Timeout occurred"


def test_installation_error_is_invoker_error() -> None:
    """Test InstallationError inherits from InvokerError."""
    error = InstallationError("Installation failed")
    assert isinstance(error, InvokerError)
    assert isinstance(error, Exception)
    assert str(error) == "Installation failed"


def test_exceptions_can_be_raised_and_caught() -> None:
    """Test exceptions can be raised and caught properly."""
    with pytest.raises(InvokerError):
        raise InvokerError("Generic error")

    with pytest.raises(InvocationTimeoutError):
        raise InvocationTimeoutError("Timeout")

    with pytest.raises(InstallationError):
        raise InstallationError("Install failed")


def test_catch_specific_exception() -> None:
    """Test catching specific exception types."""
    with pytest.raises(InvocationTimeoutError) as excinfo:
        raise InvocationTimeoutError("Timeout")
    assert str(excinfo.value) == "Timeout"
    assert isinstance(excinfo.value, InvokerError)


def test_catch_base_exception() -> None:
    """Test catching derived exceptions with base class."""
    with pytest.raises(InvokerError) as excinfo:
        raise InvocationTimeoutError("Timeout")
    assert str(excinfo.value) == "Timeout"


def test_exception_with_empty_message() -> None:
    """Test exceptions can be raised with empty message."""
    error = InvokerError("")
    assert str(error) == ""


def test_exception_with_multiline_message() -> None:
    """Test exceptions can handle multiline messages."""
    message = "Line 1\nLine 2\nLine 3"
    error = InvokerError(message)
    assert str(error) == message

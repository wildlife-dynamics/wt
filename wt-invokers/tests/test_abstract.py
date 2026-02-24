"""Tests for AbstractInvoker interface.

This module tests that the AbstractInvoker interface is properly defined
and that concrete implementations must implement all required methods.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from rattler import MatchSpec

from wt_invokers.abstract import AbstractInvoker


@dataclass
class ConcreteInvoker(AbstractInvoker):
    """Minimal concrete implementation for testing."""

    async def is_installed(self) -> bool:
        """Check if workflow is installed."""
        return True

    async def install(self) -> None:
        """Install the workflow."""
        pass

    async def run(
        self,
        workflow_run_id: str,
        config_text: str,
        results_url: str,
        execution_mode: str,
        mock_io: bool,
        otel_exporter: str | None = None,
        otel_console_exporter_dst: str | None = None,
        extra_env: dict[str, str] | None = None,
        lithops_config_text: str | None = None,
        **kwargs,
    ) -> None:
        """Run the workflow."""
        pass

    async def wait(
        self,
        timeout: float | None = None,
        error_msg: str | None = None,
    ) -> int:
        """Wait for completion."""
        return 0

    @property
    def is_waitable(self) -> bool:
        """Check if waitable."""
        return True


def test_abstract_invoker_cannot_be_instantiated() -> None:
    """Test that AbstractInvoker cannot be instantiated directly."""
    matchspec = MatchSpec("test-workflow>=1.0.0")

    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        # Type ignore because we're intentionally trying to instantiate an ABC
        AbstractInvoker(matchspec=matchspec)  # type: ignore[abstract]


def test_concrete_invoker_can_be_instantiated() -> None:
    """Test that a concrete implementation can be instantiated."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = ConcreteInvoker(matchspec=matchspec)

    assert invoker.matchspec == matchspec
    assert isinstance(invoker, AbstractInvoker)


@pytest.mark.asyncio
async def test_concrete_invoker_implements_all_methods() -> None:
    """Test that all abstract methods are implemented."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = ConcreteInvoker(matchspec=matchspec)

    # Test is_installed
    assert await invoker.is_installed() is True

    # Test install
    await invoker.install()  # Should not raise

    # Test run
    await invoker.run(
        workflow_run_id="test-run",
        config_text="param: value",
        results_url="file:///tmp/results",
        execution_mode="sequential",
        mock_io=False,
    )

    # Test wait
    exit_code = await invoker.wait()
    assert exit_code == 0

    # Test is_waitable
    assert invoker.is_waitable is True


def test_matchspec_attribute_is_accessible() -> None:
    """Test that matchspec attribute is accessible."""
    matchspec = MatchSpec("test-workflow>=1.0.0")
    invoker = ConcreteInvoker(matchspec=matchspec)

    assert invoker.matchspec.name.normalized == "test-workflow"


@dataclass
class IncompleteInvoker(AbstractInvoker):
    """Invoker missing some abstract methods (for testing)."""

    async def is_installed(self) -> bool:
        """Check if workflow is installed."""
        return True

    # Missing: install, run, wait, is_waitable


def test_incomplete_invoker_cannot_be_instantiated() -> None:
    """Test that invoker with missing methods cannot be instantiated."""
    matchspec = MatchSpec("test-workflow>=1.0.0")

    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        # Type ignore because we're intentionally creating an incomplete implementation
        IncompleteInvoker(matchspec=matchspec)  # type: ignore[abstract]

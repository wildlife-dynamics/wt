"""Tests for AbstractInvoker interface.

This module tests that the AbstractInvoker interface is properly defined
and that concrete implementations must implement all required methods.
It also exercises the ``run()``/``wait()`` lifecycle wrappers, hook
ordering, and the ``run_args`` / ``run_state`` plumbing.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import pytest
from rattler import MatchSpec

from wt_invokers.abstract import AbstractInvoker


@dataclass
class ConcreteInvoker(AbstractInvoker):
    """Minimal concrete implementation for testing."""

    async def is_installed(self) -> bool:
        return True

    async def install(self) -> None:
        pass

    async def _run(
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
        **kwargs: Any,
    ) -> None:
        pass

    async def _wait(
        self,
        timeout: float | None = None,
        error_msg: str | None = None,
    ) -> int:
        return 0

    @property
    def is_waitable(self) -> bool:
        return True


def test_abstract_invoker_cannot_be_instantiated() -> None:
    """Test that AbstractInvoker cannot be instantiated directly."""
    matchspec = MatchSpec("test-workflow>=1.0.0")

    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
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

    assert await invoker.is_installed() is True
    await invoker.install()

    await invoker.run(
        workflow_run_id="test-run",
        config_text="param: value",
        results_url="file:///tmp/results",
        execution_mode="sequential",
        mock_io=False,
    )
    exit_code = await invoker.wait()
    assert exit_code == 0

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
        return True


def test_incomplete_invoker_cannot_be_instantiated() -> None:
    """Test that invoker with missing methods cannot be instantiated."""
    matchspec = MatchSpec("test-workflow>=1.0.0")

    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        IncompleteInvoker(matchspec=matchspec)  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Lifecycle / hooks tests
# ---------------------------------------------------------------------------


def _basic_run_kwargs() -> dict[str, Any]:
    return {
        "workflow_run_id": "run-1",
        "config_text": "param: value",
        "results_url": "file:///tmp/r",
        "execution_mode": "sequential",
        "mock_io": False,
    }


@pytest.mark.asyncio
async def test_run_populates_run_args() -> None:
    """run() populates run_args with all args + kwargs during _run()."""
    captured: dict[str, Any] = {}

    @dataclass
    class Capturing(ConcreteInvoker):
        async def _run(
            self,
            workflow_run_id: str,
            config_text: str,
            results_url: str,
            execution_mode: str,
            mock_io: bool,
            **kwargs: Any,
        ) -> None:
            captured.update(self.run_args)

    invoker = Capturing(matchspec=MatchSpec("w>=1.0.0"))
    await invoker.run(
        **_basic_run_kwargs(),
        environment_tar_url="https://x/env.tar",
    )
    await invoker.wait()

    assert captured["workflow_run_id"] == "run-1"
    assert captured["config_text"] == "param: value"
    assert captured["environment_tar_url"] == "https://x/env.tar"


@pytest.mark.asyncio
async def test_run_args_is_immutable_mappingproxy() -> None:
    """run_args returns a MappingProxyType view that cannot be mutated."""
    views: list[MappingProxyType[str, Any]] = []

    @dataclass
    class Capturing(ConcreteInvoker):
        async def _run(
            self,
            workflow_run_id: str,
            config_text: str,
            results_url: str,
            execution_mode: str,
            mock_io: bool,
            **kwargs: Any,
        ) -> None:
            view = self.run_args
            views.append(view)
            assert view["workflow_run_id"] == "run-1"
            assert view["extra_kw"] == "hello"
            with pytest.raises(TypeError):
                view["workflow_run_id"] = "evil"  # type: ignore[index]

    inv = Capturing(matchspec=MatchSpec("w>=1.0.0"))
    await inv.run(**_basic_run_kwargs(), extra_kw="hello")
    await inv.wait()

    assert len(views) == 1
    assert isinstance(views[0], MappingProxyType)


@pytest.mark.asyncio
async def test_run_args_empty_when_idle() -> None:
    """run_args is empty before run() and after wait()."""
    inv = ConcreteInvoker(matchspec=MatchSpec("w>=1.0.0"))
    assert dict(inv.run_args) == {}
    await inv.run(**_basic_run_kwargs())
    await inv.wait()
    assert dict(inv.run_args) == {}


@pytest.mark.asyncio
async def test_is_running_transitions() -> None:
    """is_running flips True during run() and back to False after wait()."""
    states: list[bool] = []

    @dataclass
    class Capturing(ConcreteInvoker):
        async def _run(
            self,
            workflow_run_id: str,
            config_text: str,
            results_url: str,
            execution_mode: str,
            mock_io: bool,
            **kwargs: Any,
        ) -> None:
            states.append(self.is_running)

    inv = Capturing(matchspec=MatchSpec("w>=1.0.0"))
    assert inv.is_running is False
    await inv.run(**_basic_run_kwargs())
    assert inv.is_running is True
    await inv.wait()
    assert inv.is_running is False
    assert states == [True]


@pytest.mark.asyncio
async def test_run_raises_when_already_running() -> None:
    """Re-entering run() before wait() raises RuntimeError."""
    inv = ConcreteInvoker(matchspec=MatchSpec("w>=1.0.0"))
    await inv.run(**_basic_run_kwargs())
    with pytest.raises(RuntimeError, match="already running"):
        await inv.run(**_basic_run_kwargs())
    await inv.wait()


@pytest.mark.asyncio
async def test_multiple_run_wait_cycles() -> None:
    """After wait(), run() can be called again."""

    @dataclass
    class Cycling(ConcreteInvoker):
        async def _run(self, **kwargs: Any) -> None:
            self.run_state["ran"] = True

    inv = Cycling(matchspec=MatchSpec("w>=1.0.0"))
    await inv.run(**_basic_run_kwargs())
    await inv.wait()
    assert inv.run_state == {}
    assert dict(inv.run_args) == {}
    assert inv.is_running is False

    await inv.run(**_basic_run_kwargs())
    await inv.wait()
    assert inv.is_running is False


@pytest.mark.asyncio
async def test_non_waitable_reruns_without_wait() -> None:
    """Non-waitable invokers can call run() repeatedly without wait()."""
    call_count = 0

    @dataclass
    class FireAndForget(AbstractInvoker):
        async def is_installed(self) -> bool:
            return True

        async def install(self) -> None:
            pass

        async def _run(self, **kwargs: Any) -> None:
            nonlocal call_count
            call_count += 1
            self.run_state["last_id"] = kwargs["workflow_run_id"]

        async def _wait(
            self, timeout: float | None = None, error_msg: str | None = None
        ) -> int:
            return 0

        @property
        def is_waitable(self) -> bool:
            return False

    inv = FireAndForget(matchspec=MatchSpec("w>=1.0.0"))
    await inv.run(**{**_basic_run_kwargs(), "workflow_run_id": "a"})
    assert inv.is_running is False
    assert inv.run_state == {}
    assert dict(inv.run_args) == {}

    await inv.run(**{**_basic_run_kwargs(), "workflow_run_id": "b"})
    assert call_count == 2
    assert inv.is_running is False


@pytest.mark.asyncio
async def test_hooks_run_in_order() -> None:
    """run() calls _pre_run then _run; wait() calls _wait then _post_run."""
    calls: list[str] = []

    @dataclass
    class Ordered(AbstractInvoker):
        async def is_installed(self) -> bool:
            return True

        async def install(self) -> None:
            pass

        async def _pre_run(self) -> None:
            calls.append("pre")

        async def _run(self, **kwargs: Any) -> None:
            calls.append("run")

        async def _wait(
            self, timeout: float | None = None, error_msg: str | None = None
        ) -> int:
            calls.append("wait")
            return 0

        async def _post_run(self) -> None:
            calls.append("post")

        @property
        def is_waitable(self) -> bool:
            return True

    inv = Ordered(matchspec=MatchSpec("w>=1.0.0"))
    await inv.run(**_basic_run_kwargs())
    await inv.wait()
    assert calls == ["pre", "run", "wait", "post"]


@pytest.mark.asyncio
async def test_pre_run_failure_resets_state() -> None:
    """If _pre_run() raises, state is cleared and is_running resets."""

    @dataclass
    class Failing(ConcreteInvoker):
        async def _pre_run(self) -> None:
            raise ValueError("pre failed")

    inv = Failing(matchspec=MatchSpec("w>=1.0.0"))
    with pytest.raises(ValueError, match="pre failed"):
        await inv.run(**_basic_run_kwargs())

    assert inv.is_running is False
    assert dict(inv.run_args) == {}
    assert inv.run_state == {}


@pytest.mark.asyncio
async def test_run_failure_resets_state() -> None:
    """If _run() raises, state is cleared and is_running resets."""

    @dataclass
    class Failing(AbstractInvoker):
        async def is_installed(self) -> bool:
            return True

        async def install(self) -> None:
            pass

        async def _run(self, **kwargs: Any) -> None:
            raise ValueError("run failed")

        async def _wait(
            self, timeout: float | None = None, error_msg: str | None = None
        ) -> int:
            return 0

        @property
        def is_waitable(self) -> bool:
            return True

    inv = Failing(matchspec=MatchSpec("w>=1.0.0"))
    with pytest.raises(ValueError, match="run failed"):
        await inv.run(**_basic_run_kwargs())

    assert inv.is_running is False
    assert dict(inv.run_args) == {}
    assert inv.run_state == {}


@pytest.mark.asyncio
async def test_post_run_runs_on_non_zero_exit() -> None:
    """_post_run runs even when _wait returns non-zero."""
    calls: list[str] = []

    @dataclass
    class NonZero(AbstractInvoker):
        async def is_installed(self) -> bool:
            return True

        async def install(self) -> None:
            pass

        async def _run(self, **kwargs: Any) -> None:
            pass

        async def _wait(
            self, timeout: float | None = None, error_msg: str | None = None
        ) -> int:
            return 42

        async def _post_run(self) -> None:
            calls.append("post")

        @property
        def is_waitable(self) -> bool:
            return True

    inv = NonZero(matchspec=MatchSpec("w>=1.0.0"))
    await inv.run(**_basic_run_kwargs())
    exit_code = await inv.wait()
    assert exit_code == 42
    assert calls == ["post"]
    assert inv.is_running is False


@pytest.mark.asyncio
async def test_post_run_runs_on_wait_exception() -> None:
    """_post_run runs even when _wait raises; state still resets."""
    calls: list[str] = []

    @dataclass
    class WaitRaises(AbstractInvoker):
        async def is_installed(self) -> bool:
            return True

        async def install(self) -> None:
            pass

        async def _run(self, **kwargs: Any) -> None:
            pass

        async def _wait(
            self, timeout: float | None = None, error_msg: str | None = None
        ) -> int:
            raise RuntimeError("boom")

        async def _post_run(self) -> None:
            calls.append("post")

        @property
        def is_waitable(self) -> bool:
            return True

    inv = WaitRaises(matchspec=MatchSpec("w>=1.0.0"))
    await inv.run(**_basic_run_kwargs())
    with pytest.raises(RuntimeError, match="boom"):
        await inv.wait()
    assert calls == ["post"]
    assert inv.is_running is False
    assert dict(inv.run_args) == {}


@pytest.mark.asyncio
async def test_post_run_failure_still_clears_state() -> None:
    """If _post_run raises, state is still cleaned up."""

    @dataclass
    class PostRaises(ConcreteInvoker):
        async def _post_run(self) -> None:
            raise RuntimeError("post failed")

    inv = PostRaises(matchspec=MatchSpec("w>=1.0.0"))
    await inv.run(**_basic_run_kwargs())
    with pytest.raises(RuntimeError, match="post failed"):
        await inv.wait()
    assert inv.is_running is False
    assert dict(inv.run_args) == {}
    assert inv.run_state == {}


@pytest.mark.asyncio
async def test_wait_idle_skips_post_run() -> None:
    """wait() from IDLE raises immediately and does not invoke _post_run.

    Pins the lifecycle guard: previously, calling wait() with no prior run()
    let _wait raise "Process not started" and then _post_run ran with empty
    run_args, failing its own preconditions and masking the real error.
    """
    post_run_called = False

    @dataclass
    class PostRunTracker(ConcreteInvoker):
        async def _post_run(self) -> None:
            nonlocal post_run_called
            post_run_called = True

    inv = PostRunTracker(matchspec=MatchSpec("w>=1.0.0"))
    with pytest.raises(RuntimeError, match="not running"):
        await inv.wait()
    assert post_run_called is False
    assert inv.is_running is False


@pytest.mark.asyncio
async def test_pre_and_post_run_default_to_no_ops() -> None:
    """Default _pre_run and _post_run do nothing."""
    inv = ConcreteInvoker(matchspec=MatchSpec("w>=1.0.0"))
    await inv.run(**_basic_run_kwargs())
    await inv.wait()
    assert inv.run_state == {}

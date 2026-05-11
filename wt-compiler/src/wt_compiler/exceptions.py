"""Custom exceptions for wt-compiler.

This module defines exceptions for task discovery errors, providing
clear and actionable error messages when the wt-registry CLI is not
found or fails during execution.

Examples:
    >>> from pathlib import Path
    >>> from rattler import MatchSpec
    >>> error = RegistryNotFoundError(
    ...     executable_path=Path("/tmp/env/bin/wt-registry"),
    ...     requirements=[MatchSpec("my-package>=1.0.0")],
    ... )
    >>> "wt-registry executable not found" in str(error)
    True
"""
# ruff: noqa: D105, D107  # exception __init__/__str__ are documented at the class level

from __future__ import annotations

import errno
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from rattler import MatchSpec

    from wt_compiler.spec import PyPIRequirement


class DiscoveryError(Exception):
    """Base exception for all task discovery errors.

    All custom exceptions related to task discovery in wt-compiler
    inherit from this class, making it easy to catch any discovery-related error.

    Examples:
        >>> try:
        ...     raise DiscoveryError("Discovery failed")
        ... except DiscoveryError as e:
        ...     print(f"Caught: {e}")
        Caught: Discovery failed
    """


class RegistryNotFoundError(DiscoveryError):
    """Raised when wt-registry CLI is not found in the ephemeral environment.

    This error occurs when the ephemeral conda environment created for task
    discovery does not contain the wt-registry executable. This typically
    happens when none of the specified packages depend on wt-registry.

    Attributes:
        executable_path: Expected path to wt-registry executable
        requirements: List of MatchSpec requirements that were installed

    Examples:
        >>> from pathlib import Path
        >>> from rattler import MatchSpec
        >>> error = RegistryNotFoundError(
        ...     executable_path=Path("/tmp/env/bin/wt-registry"),
        ...     requirements=[MatchSpec("my-tasks>=1.0.0")],
        ... )
        >>> "/tmp/env/bin/wt-registry" in str(error)
        True
        >>> "wt-registry" in str(error)  # Fix suggestion included
        True
    """

    def __init__(
        self,
        executable_path: Path,
        requirements: list[MatchSpec],
    ) -> None:
        self.executable_path = executable_path
        self.requirements = requirements
        super().__init__(str(self))

    def __str__(self) -> str:
        req_list = "\n".join(f"  - {req}" for req in self.requirements)
        return f"""wt-registry executable not found at '{self.executable_path}'

The ephemeral environment was created with the following packages:
{req_list}

The wt-registry CLI is required for task discovery but was not installed
because none of the specified packages depend on wt-registry.

To fix this issue, ensure your task packages include wt-registry as a dependency:
  1. Add 'wt-registry' to your package's conda dependencies, OR
  2. Add 'wt-registry' to the requirements in your spec.yaml"""


class RegistryExecutionError(DiscoveryError):
    """Raised when wt-registry CLI fails during execution.

    This error occurs when the wt-registry CLI is found but returns a
    non-zero exit code. The error includes stdout and stderr from the
    failed command to aid debugging.

    Attributes:
        executable_path: Path to wt-registry executable that was run
        returncode: Exit code from the failed command
        stdout: Standard output from the command
        stderr: Standard error from the command
        requirements: List of MatchSpec requirements that were installed

    Examples:
        >>> from pathlib import Path
        >>> from rattler import MatchSpec
        >>> error = RegistryExecutionError(
        ...     executable_path=Path("/tmp/env/bin/wt-registry"),
        ...     returncode=1,
        ...     stdout="",
        ...     stderr="ImportError: No module named 'foo'",
        ...     requirements=[MatchSpec("my-tasks>=1.0.0")],
        ... )
        >>> "exit code 1" in str(error)
        True
        >>> "ImportError" in str(error)
        True
    """

    def __init__(
        self,
        executable_path: Path,
        returncode: int,
        stdout: str,
        stderr: str,
        requirements: list[MatchSpec],
    ) -> None:
        self.executable_path = executable_path
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.requirements = requirements
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"""wt-registry CLI failed with exit code {self.returncode}

Command: {self.executable_path} --format json

stdout:
{self.stdout or "(empty)"}

stderr:
{self.stderr or "(empty)"}

This may indicate:
  - An incompatible version of wt-registry
  - Missing dependencies in the environment
  - A bug in wt-registry or registered task functions"""


class PyPIInstallError(DiscoveryError):
    """Raised when the bulk pip install of PyPI requirements fails.

    This error occurs after the conda environment is created but the bulk
    ``uv pip install`` call (covering all PyPI dependencies at once) fails.
    Because the install is a single subprocess invocation, the failure is
    shared across every requirement in the batch.

    Attributes:
        requirements: All PyPIRequirements that were passed to the failed
            ``uv pip install`` invocation
        returncode: Exit code from the pip install command
        stdout: Standard output from pip
        stderr: Standard error from pip

    Examples:
        >>> from wt_compiler.spec import PyPIRequirement
        >>> req = PyPIRequirement(name="foo", git="https://github.com/org/foo.git")
        >>> error = PyPIInstallError(
        ...     requirements=[req],
        ...     returncode=1,
        ...     stdout="",
        ...     stderr="ERROR: Could not find a version that satisfies the requirement",
        ... )
        >>> "foo" in str(error)
        True
    """

    def __init__(
        self,
        requirements: list[PyPIRequirement],
        returncode: int,
        stdout: str,
        stderr: str,
    ) -> None:
        self.requirements = requirements
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(str(self))

    def __str__(self) -> str:
        names = ", ".join(r.name for r in self.requirements) or "(none)"
        install_args = "\n".join(f"  {r.to_pip_install_arg()}" for r in self.requirements)
        return f"""pip install failed for PyPI requirements [{names}] (exit code {self.returncode})

Install arguments:
{install_args}

stdout:
{self.stdout or "(empty)"}

stderr:
{self.stderr or "(empty)"}"""


class EnvironmentCreationError(DiscoveryError):
    """Raised when ephemeral environment creation fails.

    This error occurs when py-rattler fails to solve dependencies or install
    packages into the ephemeral environment. The error includes context about
    which phase failed and provides guidance based on the error type.

    Attributes:
        env_path: Path to the environment that failed to create
        requirements: List of MatchSpec requirements that were being installed
        original_error: The underlying exception that caused the failure
        phase: Which phase failed - "solve" or "install"

    Examples:
        >>> from pathlib import Path
        >>> from rattler import MatchSpec
        >>> error = EnvironmentCreationError(
        ...     env_path=Path("/tmp/env"),
        ...     requirements=[MatchSpec("my-package>=1.0.0")],
        ...     original_error=OSError(66, "Directory not empty"),
        ...     phase="install",
        ... )
        >>> "install" in str(error)
        True
        >>> "Directory not empty" in str(error)
        True
    """

    def __init__(
        self,
        env_path: Path,
        requirements: list[MatchSpec],
        original_error: Exception,
        phase: str,
    ) -> None:
        self.env_path = env_path
        self.requirements = requirements
        self.original_error = original_error
        self.phase = phase
        super().__init__(str(self))

    def __str__(self) -> str:
        req_list = "\n".join(f"  - {req}" for req in self.requirements)
        base_msg = f"""Environment creation failed during {self.phase} phase

Target environment: {self.env_path}

Requirements:
{req_list}

Error: {self.original_error}"""

        # Add specific guidance based on error type
        guidance = ""
        if isinstance(self.original_error, OSError):
            if self.original_error.errno == errno.ENOTEMPTY:
                guidance = """
This is a race condition in parallel package installation (ENOTEMPTY).
The installation was retried but still failed. This may indicate:
  - Extremely high filesystem contention
  - A corrupted package cache
Try running the command again, or clear the rattler cache."""
            elif self.original_error.errno == errno.EMFILE:
                guidance = """
Too many open files (EMFILE). Try:
  - Increasing the file descriptor limit: ulimit -n 4096
  - Reducing parallelism in package installation"""

        if self.phase == "solve":
            guidance = """
Dependency resolution failed. This may indicate:
  - Package not found on the specified channels
  - Conflicting version constraints
  - Missing or invalid channel configuration"""

        return base_msg + guidance

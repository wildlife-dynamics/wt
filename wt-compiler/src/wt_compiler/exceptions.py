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

from pathlib import Path

from rattler import MatchSpec


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

    pass


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

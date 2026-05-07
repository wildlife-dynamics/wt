"""Wrapper for invoking the wt-compiler CLI."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class CompileResult:
    """Result of a compilation operation."""

    exit_code: int
    stdout: str
    stderr: str
    spec_path: Path
    generated_path: Path | None

    @property
    def success(self) -> bool:
        """Return True if compilation succeeded."""
        return self.exit_code == 0


def _compile_flags_to_args(compile_flags: dict[str, str]) -> list[str]:
    """Convert compile_flags dict to CLI arguments.

    Args:
        compile_flags: Dict mapping flag names (underscore style) to values.
            Supported keys: pkg_name_prefix, results_env_var, variant.

    Returns:
        List of CLI argument strings (e.g., ["--pkg-name-prefix=value"]).
    """
    args: list[str] = []
    for key, value in compile_flags.items():
        cli_flag = f"--{key.replace('_', '-')}"
        args.append(f"{cli_flag}={value}")
    return args


def run_compiler(
    spec_path: Path,
    clobber: bool = True,
    update: bool = False,
    timeout: int = 300,
    compile_flags: dict[str, str] | None = None,
) -> CompileResult:
    """Run the wt-compiler CLI to compile a workflow spec.

    Args:
        spec_path: Path to the spec.yaml file
        clobber: If True, overwrite existing output directory
        update: If True, carry over lockfile and bump version
        timeout: Timeout in seconds for the compilation process
        compile_flags: Optional dict of compiler flags (e.g., pkg_name_prefix, variant)

    Returns:
        CompileResult with exit code, stdout, stderr, and paths

    Note:
        The compiler outputs to a sibling directory of spec_path named
        after the spec's id (e.g., wf-{spec_id}/).
    """
    cmd = [
        sys.executable,
        "-m",
        "wt_compiler",
        "compile",
        "--spec",
        str(spec_path),
    ]

    if clobber:
        cmd.append("--clobber")
    if update:
        cmd.append("--update")
    if compile_flags:
        cmd.extend(_compile_flags_to_args(compile_flags))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=spec_path.parent,
    )

    # Try to determine the generated path from the spec
    # The compiler creates {pkg_name_prefix}-{spec_id}-workflow/ as a sibling to spec.yaml
    generated_path = None
    if result.returncode == 0:
        # Look for the generated directory
        for path in spec_path.parent.iterdir():
            if path.is_dir() and path.name.endswith("-workflow"):
                generated_path = path
                break

    return CompileResult(
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        spec_path=spec_path,
        generated_path=generated_path,
    )


def compile_workflow(
    repo_path: Path,
    spec_path: str = "spec.yaml",
    generated_path: str | None = None,
    clobber: bool = True,
    update: bool = False,
    timeout: int = 300,
    compile_flags: dict[str, str] | None = None,
) -> CompileResult:
    """Compile a workflow in a cloned repository.

    Args:
        repo_path: Path to the cloned repository root
        spec_path: Relative path to spec.yaml within the repo
        generated_path: Expected path to generated package (for validation)
        clobber: If True, overwrite existing output directory
        update: If True, carry over lockfile and bump version
        timeout: Timeout in seconds
        compile_flags: Optional dict of compiler flags (e.g., pkg_name_prefix, variant)

    Returns:
        CompileResult with compilation details

    Raises:
        FileNotFoundError: If spec_path does not exist
    """
    full_spec_path = repo_path / spec_path

    if not full_spec_path.exists():
        raise FileNotFoundError(f"Spec file not found: {full_spec_path}")

    result = run_compiler(
        full_spec_path,
        clobber=clobber,
        update=update,
        timeout=timeout,
        compile_flags=compile_flags,
    )

    # If generated_path was provided, verify it matches
    if result.success and generated_path:
        expected_path = repo_path / generated_path
        if expected_path.exists() and result.generated_path != expected_path:
            result = CompileResult(
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                spec_path=result.spec_path,
                generated_path=expected_path,
            )

    return result

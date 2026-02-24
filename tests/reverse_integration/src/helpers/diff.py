"""Diff checking utilities for verifying recompilation results."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DiffResult:
    """Result of a diff check operation."""

    changed_files: list[str]
    allowed_changes: list[str]
    unexpected_changes: list[str]

    @property
    def has_unexpected_changes(self) -> bool:
        """Return True if there are unexpected changes."""
        return len(self.unexpected_changes) > 0


def get_changed_files(repo_path: Path) -> list[str]:
    """
    Get list of files that have changed in a git repository.

    This includes both staged and unstaged changes, as well as untracked files.

    Args:
        repo_path: Path to the git repository

    Returns:
        List of relative file paths that have changed

    Raises:
        subprocess.CalledProcessError: If git commands fail
    """
    changed = set()

    # Get modified and staged files
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    changed.update(line.strip() for line in result.stdout.splitlines() if line.strip())

    # Get staged files
    result = subprocess.run(
        ["git", "diff", "--name-only", "--cached"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    changed.update(line.strip() for line in result.stdout.splitlines() if line.strip())

    # Get untracked files
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    changed.update(line.strip() for line in result.stdout.splitlines() if line.strip())

    return sorted(changed)


def check_diff_allowlist(
    changed_files: list[str],
    allowlist: list[str],
    generated_path: str | None = None,
) -> DiffResult:
    """
    Check if changed files are within the allowlist.

    Args:
        changed_files: List of changed file paths
        allowlist: List of file basenames that are allowed to change
        generated_path: Optional prefix for generated package path

    Returns:
        DiffResult with categorized changes

    Examples:
        >>> check_diff_allowlist(
        ...     ["README.md", "pixi.lock", "src/main.py"],
        ...     ["README.md", "pixi.lock"]
        ... )
        DiffResult(
            changed_files=["README.md", "pixi.lock", "src/main.py"],
            allowed_changes=["README.md", "pixi.lock"],
            unexpected_changes=["src/main.py"]
        )
    """
    allowed = []
    unexpected = []

    for file_path in changed_files:
        # Check if the file basename is in the allowlist
        basename = Path(file_path).name
        is_allowed = basename in allowlist

        # Also check if it's a nested path within generated package
        if generated_path and file_path.startswith(generated_path):
            relative = file_path[len(generated_path) :].lstrip("/")
            nested_basename = Path(relative).name
            is_allowed = is_allowed or nested_basename in allowlist

        if is_allowed:
            allowed.append(file_path)
        else:
            unexpected.append(file_path)

    return DiffResult(
        changed_files=changed_files,
        allowed_changes=allowed,
        unexpected_changes=unexpected,
    )


def format_diff_report(diff_result: DiffResult) -> str:
    """
    Format a diff result into a human-readable report.

    Args:
        diff_result: The DiffResult to format

    Returns:
        Formatted string report
    """
    lines = []

    if diff_result.unexpected_changes:
        lines.append("UNEXPECTED CHANGES:")
        for f in diff_result.unexpected_changes:
            lines.append(f"  - {f}")
        lines.append("")

    if diff_result.allowed_changes:
        lines.append("Allowed changes (expected):")
        for f in diff_result.allowed_changes:
            lines.append(f"  - {f}")

    if not diff_result.changed_files:
        lines.append("No changes detected.")

    return "\n".join(lines)

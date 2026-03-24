"""Diff checking utilities for verifying recompilation results."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MASK_PLACEHOLDER = "<MASKED>"


@dataclass
class VarianceCheckResult:
    """Result of checking allowed variance for a single file."""

    passed: bool
    removed: list[str]
    added: list[str]
    norm_removed: list[str]
    norm_added: list[str]
    diagnostics: list[str]


@dataclass
class ConditionalAllowEntry:
    """A diff allowlist entry with conditional variance patterns."""

    file: str
    allowed_variance: list[str]


@dataclass
class DiffResult:
    """Result of a diff check operation."""

    changed_files: list[str]
    allowed_changes: list[str]
    unexpected_changes: list[str]
    conditionally_allowed: list[str] = field(default_factory=list)
    variance_results: dict[str, VarianceCheckResult] = field(default_factory=dict)

    @property
    def has_unexpected_changes(self) -> bool:
        """Return True if there are unexpected changes."""
        return len(self.unexpected_changes) > 0


def parse_allowlist(
    raw: list[str | dict[str, Any]],
) -> tuple[list[str], list[ConditionalAllowEntry]]:
    """
    Parse a mixed allowlist into simple entries and conditional entries.

    Args:
        raw: List of allowlist entries (strings or dicts with file/allowed_variance)

    Returns:
        Tuple of (simple_basenames, conditional_entries)

    Examples:
        >>> simple, conditional = parse_allowlist([
        ...     "README.md",
        ...     {"file": "Dockerfile", "allowed_variance": [r"PIXI_VERSION=\\S+"]},
        ... ])
        >>> simple
        ['README.md']
        >>> conditional[0].file
        'Dockerfile'
    """
    simple: list[str] = []
    conditional: list[ConditionalAllowEntry] = []

    for entry in raw:
        if isinstance(entry, str):
            simple.append(entry)
        elif isinstance(entry, dict):
            conditional.append(
                ConditionalAllowEntry(
                    file=entry["file"],
                    allowed_variance=entry["allowed_variance"],
                )
            )

    return simple, conditional


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


def get_file_diff(repo_path: Path, file_path: str) -> str:
    """
    Get the unified diff for a specific file.

    Args:
        repo_path: Path to the git repository
        file_path: Relative path to the file within the repo

    Returns:
        Unified diff output as a string
    """
    result = subprocess.run(
        ["git", "diff", "--", file_path],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def normalize_line(line: str, patterns: list[re.Pattern[str]]) -> str:
    """
    Apply all pattern substitutions to a line, replacing matches with a placeholder.

    Args:
        line: The line to normalize
        patterns: Compiled regex patterns to mask

    Returns:
        The line with all pattern matches replaced by MASK_PLACEHOLDER
    """
    for pattern in patterns:
        line = pattern.sub(MASK_PLACEHOLDER, line)
    return line


def check_allowed_variance(
    diff_output: str,
    patterns: list[str],
) -> VarianceCheckResult:
    """
    Check if a file's diff only changes in regions matching the given patterns.

    Uses normalization: replaces pattern matches with a placeholder in both
    removed and added lines. If normalized sequences are identical, only the
    masked regions actually changed.

    Args:
        diff_output: Unified diff output for a single file
        patterns: List of regex pattern strings to mask

    Returns:
        VarianceCheckResult with full trace for verbose output
    """
    compiled = [re.compile(p) for p in patterns]
    removed: list[str] = []
    added: list[str] = []

    for line in diff_output.splitlines():
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("@@"):
            continue
        if line.startswith("-"):
            removed.append(line[1:])
        elif line.startswith("+"):
            added.append(line[1:])

    norm_removed = [normalize_line(line, compiled) for line in removed]
    norm_added = [normalize_line(line, compiled) for line in added]

    passed = norm_removed == norm_added
    diagnostics: list[str] = []
    if not passed:
        if len(norm_removed) != len(norm_added):
            diagnostics.append(
                f"Line count changed: {len(removed)} removed, {len(added)} added"
            )
        else:
            for i, (r, a) in enumerate(zip(norm_removed, norm_added, strict=True)):
                if r != a:
                    diagnostics.append(f"Line {i + 1} differs after normalization:")
                    diagnostics.append(f"  - {removed[i]}")
                    diagnostics.append(f"  + {added[i]}")

    return VarianceCheckResult(
        passed=passed,
        removed=removed,
        added=added,
        norm_removed=norm_removed,
        norm_added=norm_added,
        diagnostics=diagnostics,
    )


def check_diff_allowlist(
    changed_files: list[str],
    allowlist: list[str | dict[str, Any]],
    generated_path: str | None = None,
    repo_path: Path | None = None,
) -> DiffResult:
    """
    Check if changed files are within the allowlist.

    Supports both simple string entries (any change allowed) and conditional
    entries with allowed_variance patterns (only masked regions may change).

    Args:
        changed_files: List of changed file paths
        allowlist: List of file basenames (str) or conditional entries (dict)
        generated_path: Optional prefix for generated package path
        repo_path: Path to the git repository (required for conditional entries)

    Returns:
        DiffResult with categorized changes

    Examples:
        >>> result = check_diff_allowlist(
        ...     ["README.md", "pixi.lock", "src/main.py"],
        ...     ["README.md", "pixi.lock"],
        ... )
        >>> result.allowed_changes
        ['README.md', 'pixi.lock']
        >>> result.unexpected_changes
        ['src/main.py']
    """
    simple_entries, conditional_entries = parse_allowlist(allowlist)

    # Build lookup for conditional entries by basename
    conditional_by_basename: dict[str, ConditionalAllowEntry] = {
        entry.file: entry for entry in conditional_entries
    }

    allowed: list[str] = []
    unexpected: list[str] = []
    conditionally_allowed: list[str] = []
    variance_results: dict[str, VarianceCheckResult] = {}

    for file_path in changed_files:
        basename = Path(file_path).name

        # Also check nested path within generated package
        nested_basename = None
        if generated_path and file_path.startswith(generated_path):
            relative = file_path[len(generated_path):].lstrip("/")
            nested_basename = Path(relative).name

        # 1. Check simple allowlist
        if basename in simple_entries or (nested_basename and nested_basename in simple_entries):
            allowed.append(file_path)
            continue

        # 2. Check conditional allowlist
        match_basename = None
        if basename in conditional_by_basename:
            match_basename = basename
        elif nested_basename and nested_basename in conditional_by_basename:
            match_basename = nested_basename

        if match_basename is not None and repo_path is not None:
            entry = conditional_by_basename[match_basename]
            diff_output = get_file_diff(repo_path, file_path)
            result = check_allowed_variance(diff_output, entry.allowed_variance)
            variance_results[file_path] = result

            if result.passed:
                conditionally_allowed.append(file_path)
            else:
                unexpected.append(file_path)
            continue

        # 3. No match
        unexpected.append(file_path)

    return DiffResult(
        changed_files=changed_files,
        allowed_changes=allowed,
        unexpected_changes=unexpected,
        conditionally_allowed=conditionally_allowed,
        variance_results=variance_results,
    )


def format_diff_report(diff_result: DiffResult) -> str:
    """
    Format a diff result into a human-readable report.

    Args:
        diff_result: The DiffResult to format

    Returns:
        Formatted string report
    """
    lines: list[str] = []

    if diff_result.unexpected_changes:
        lines.append("UNEXPECTED CHANGES:")
        for f in diff_result.unexpected_changes:
            lines.append(f"  - {f}")
            # Show variance diagnostics if this file had a conditional check
            if f in diff_result.variance_results:
                result = diff_result.variance_results[f]
                lines.append("    Conditional allowlist check FAILED:")
                for diag in result.diagnostics:
                    lines.append(f"      {diag}")
        lines.append("")

    if diff_result.allowed_changes:
        lines.append("Allowed changes (expected):")
        for f in diff_result.allowed_changes:
            lines.append(f"  - {f}")

    if diff_result.conditionally_allowed:
        if diff_result.allowed_changes:
            lines.append("")
        lines.append("Conditionally allowed changes (matched variance patterns):")
        for f in diff_result.conditionally_allowed:
            lines.append(f"  - {f}")

    if not diff_result.changed_files:
        lines.append("No changes detected.")

    return "\n".join(lines)


def format_variance_analysis(
    variance_results: dict[str, VarianceCheckResult],
    conditional_entries: list[ConditionalAllowEntry],
) -> str:
    """
    Format detailed variance analysis for --show-diff-analysis output.

    Args:
        variance_results: Map of file paths to their variance check results
        conditional_entries: The conditional allowlist entries (for pattern info)

    Returns:
        Formatted analysis string
    """
    # Build pattern lookup by basename
    patterns_by_basename: dict[str, list[str]] = {
        entry.file: entry.allowed_variance for entry in conditional_entries
    }

    lines: list[str] = []
    for file_path, result in variance_results.items():
        basename = Path(file_path).name
        patterns = patterns_by_basename.get(basename, [])

        lines.append(f"--- Diff analysis: {basename} ---")
        lines.append(f"Patterns: {patterns}")

        for i, (rem, add) in enumerate(zip(result.removed, result.added, strict=True)):
            lines.append(f"  removed: {rem}")
            lines.append(f"  added:   {add}")
            lines.append(f"  masked-: {result.norm_removed[i]}")
            lines.append(f"  masked+: {result.norm_added[i]}")

        status = "PASS (normalized lines identical)" if result.passed else "FAIL"
        lines.append(f"  result:  {status}")

        if not result.passed:
            for diag in result.diagnostics:
                lines.append(f"    {diag}")

        lines.append("")

    return "\n".join(lines)

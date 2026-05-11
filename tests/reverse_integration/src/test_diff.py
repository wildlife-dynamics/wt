"""Unit tests for diff checking utilities, including allowed_variance."""

from __future__ import annotations

import re

from helpers.diff import (
    MASK_PLACEHOLDER,
    ConditionalAllowEntry,
    DiffResult,
    VarianceCheckResult,
    check_allowed_variance,
    check_diff_allowlist,
    format_diff_report,
    format_variance_analysis,
    normalize_line,
    parse_allowlist,
)


class TestParseAllowlist:
    """Tests for parse_allowlist()."""

    def test_simple_strings_only(self) -> None:
        simple, conditional = parse_allowlist(["README.md", "pixi.lock"])
        assert simple == ["README.md", "pixi.lock"]
        assert conditional == []

    def test_conditional_entries_only(self) -> None:
        simple, conditional = parse_allowlist(
            [
                {"file": "Dockerfile", "allowed_variance": [r"PIXI_VERSION=\S+"]},
            ]
        )
        assert simple == []
        assert len(conditional) == 1
        assert conditional[0].file == "Dockerfile"
        assert conditional[0].allowed_variance == [r"PIXI_VERSION=\S+"]

    def test_mixed_entries(self) -> None:
        raw = [
            "README.md",
            {"file": "VERSION.yaml", "allowed_variance": [r"MIN: \d+"]},
            "pixi.lock",
        ]
        simple, conditional = parse_allowlist(raw)
        assert simple == ["README.md", "pixi.lock"]
        assert len(conditional) == 1
        assert conditional[0].file == "VERSION.yaml"

    def test_empty_list(self) -> None:
        simple, conditional = parse_allowlist([])
        assert simple == []
        assert conditional == []


class TestNormalizeLine:
    """Tests for normalize_line()."""

    def test_single_pattern(self) -> None:
        patterns = [re.compile(r"PIXI_VERSION=\S+")]
        result = normalize_line("RUN curl | PIXI_VERSION=v0.66.0 bash", patterns)
        assert result == f"RUN curl | {MASK_PLACEHOLDER} bash"

    def test_multiple_patterns(self) -> None:
        patterns = [re.compile(r"MIN: \d+"), re.compile(r"PATCH: \d+")]
        result = normalize_line("{MAJ: 0, MIN: 1, PATCH: 3}", patterns)
        assert result == f"{{MAJ: 0, {MASK_PLACEHOLDER}, {MASK_PLACEHOLDER}}}"

    def test_no_match(self) -> None:
        patterns = [re.compile(r"PIXI_VERSION=\S+")]
        result = normalize_line("FROM python:3.11", patterns)
        assert result == "FROM python:3.11"

    def test_empty_patterns(self) -> None:
        result = normalize_line("some line", [])
        assert result == "some line"


class TestCheckAllowedVariance:
    """Tests for check_allowed_variance()."""

    def test_only_masked_region_changed(self) -> None:
        diff = (
            "--- a/VERSION.yaml\n"
            "+++ b/VERSION.yaml\n"
            "@@ -1 +1 @@\n"
            "-{MAJ: 0, MIN: 0, PATCH: 0}\n"
            "+{MAJ: 0, MIN: 1, PATCH: 0}\n"
        )
        result = check_allowed_variance(diff, [r"MIN: \d+"])
        assert result.passed is True
        assert result.removed == ["{MAJ: 0, MIN: 0, PATCH: 0}"]
        assert result.added == ["{MAJ: 0, MIN: 1, PATCH: 0}"]
        assert result.diagnostics == []

    def test_non_masked_region_also_changed(self) -> None:
        diff = (
            "--- a/VERSION.yaml\n"
            "+++ b/VERSION.yaml\n"
            "@@ -1 +1 @@\n"
            "-{MAJ: 0, MIN: 0, PATCH: 0}\n"
            "+{MAJ: 1, MIN: 1, PATCH: 0}\n"
        )
        result = check_allowed_variance(diff, [r"MIN: \d+"])
        assert result.passed is False
        assert len(result.diagnostics) > 0

    def test_lines_added(self) -> None:
        diff = "--- a/file.txt\n+++ b/file.txt\n@@ -1 +1,2 @@\n-old line\n+new line\n+extra line\n"
        result = check_allowed_variance(diff, [r"old|new"])
        assert result.passed is False
        assert "Line count changed" in result.diagnostics[0]

    def test_lines_removed(self) -> None:
        diff = "--- a/file.txt\n+++ b/file.txt\n@@ -1,2 +1 @@\n-line one\n-line two\n+line one\n"
        result = check_allowed_variance(diff, [r"one|two"])
        assert result.passed is False

    def test_empty_diff(self) -> None:
        result = check_allowed_variance("", [r"anything"])
        assert result.passed is True
        assert result.removed == []
        assert result.added == []

    def test_multiple_patterns(self) -> None:
        diff = (
            "--- a/Dockerfile\n"
            "+++ b/Dockerfile\n"
            "@@ -1,2 +1,2 @@\n"
            "-PIXI_VERSION=v0.66.0\n"
            "-OTHER_VERSION=1.0\n"
            "+PIXI_VERSION=v0.67.0\n"
            "+OTHER_VERSION=2.0\n"
        )
        result = check_allowed_variance(diff, [r"PIXI_VERSION=\S+", r"OTHER_VERSION=\S+"])
        assert result.passed is True

    def test_dockerfile_pixi_version(self) -> None:
        diff = (
            "--- a/Dockerfile\n"
            "+++ b/Dockerfile\n"
            "@@ -5,1 +5,1 @@\n"
            "-RUN curl -fsSL https://pixi.sh/install.sh | PIXI_VERSION=v0.66.0 bash\n"
            "+RUN curl -fsSL https://pixi.sh/install.sh | PIXI_VERSION=latest bash\n"
        )
        result = check_allowed_variance(diff, [r"PIXI_VERSION=\S+"])
        assert result.passed is True

    def test_dockerfile_pixi_version_with_other_change(self) -> None:
        diff = (
            "--- a/Dockerfile\n"
            "+++ b/Dockerfile\n"
            "@@ -5,1 +5,1 @@\n"
            "-RUN curl -fsSL https://pixi.sh/install.sh | PIXI_VERSION=v0.66.0 bash\n"
            "+RUN wget https://pixi.sh/install.sh | PIXI_VERSION=latest bash\n"
        )
        result = check_allowed_variance(diff, [r"PIXI_VERSION=\S+"])
        assert result.passed is False


class TestCheckDiffAllowlistIntegration:
    """Tests for check_diff_allowlist() with mixed allowlist types (no git needed)."""

    def test_simple_entries_still_work(self) -> None:
        result = check_diff_allowlist(
            ["README.md", "pixi.lock", "src/main.py"],
            ["README.md", "pixi.lock"],
        )
        assert result.allowed_changes == ["README.md", "pixi.lock"]
        assert result.unexpected_changes == ["src/main.py"]
        assert result.conditionally_allowed == []

    def test_conditional_without_repo_path_is_unexpected(self) -> None:
        """Conditional entries require repo_path; without it, files are unexpected."""
        result = check_diff_allowlist(
            ["Dockerfile"],
            [{"file": "Dockerfile", "allowed_variance": [r"PIXI_VERSION=\S+"]}],
        )
        assert result.unexpected_changes == ["Dockerfile"]

    def test_mixed_allowlist_simple_match(self) -> None:
        result = check_diff_allowlist(
            ["README.md", "Dockerfile"],
            [
                "README.md",
                {"file": "Dockerfile", "allowed_variance": [r"PIXI_VERSION=\S+"]},
            ],
        )
        assert result.allowed_changes == ["README.md"]
        # Dockerfile is unexpected because no repo_path
        assert result.unexpected_changes == ["Dockerfile"]

    def test_generated_path_with_simple_entry(self) -> None:
        result = check_diff_allowlist(
            ["pkg/README.md", "pkg/src/main.py"],
            ["README.md"],
            generated_path="pkg",
        )
        assert result.allowed_changes == ["pkg/README.md"]
        assert result.unexpected_changes == ["pkg/src/main.py"]


class TestFormatDiffReport:
    """Tests for format_diff_report() with conditional entries."""

    def test_includes_conditionally_allowed(self) -> None:
        result = DiffResult(
            changed_files=["README.md", "Dockerfile"],
            allowed_changes=["README.md"],
            unexpected_changes=[],
            conditionally_allowed=["Dockerfile"],
        )
        report = format_diff_report(result)
        assert "Conditionally allowed" in report
        assert "Dockerfile" in report

    def test_includes_variance_diagnostics_on_failure(self) -> None:
        result = DiffResult(
            changed_files=["Dockerfile"],
            allowed_changes=[],
            unexpected_changes=["Dockerfile"],
            variance_results={
                "Dockerfile": VarianceCheckResult(
                    passed=False,
                    removed=["old"],
                    added=["new"],
                    norm_removed=["masked_old"],
                    norm_added=["masked_new"],
                    diagnostics=["Line 1 differs after normalization:"],
                ),
            },
        )
        report = format_diff_report(result)
        assert "UNEXPECTED" in report
        assert "Conditional allowlist check FAILED" in report


class TestFormatVarianceAnalysis:
    """Tests for format_variance_analysis()."""

    def test_basic_output(self) -> None:
        entries = [ConditionalAllowEntry(file="Dockerfile", allowed_variance=[r"PIXI_VERSION=\S+"])]
        results = {
            "pkg/Dockerfile": VarianceCheckResult(
                passed=True,
                removed=["PIXI_VERSION=v0.66.0"],
                added=["PIXI_VERSION=latest"],
                norm_removed=[MASK_PLACEHOLDER],
                norm_added=[MASK_PLACEHOLDER],
                diagnostics=[],
            ),
        }
        output = format_variance_analysis(results, entries)
        assert "Dockerfile" in output
        assert "PASS" in output
        assert "PIXI_VERSION" in output

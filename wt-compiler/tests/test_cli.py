"""Tests for CLI functionality."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wt_compiler.cli import main


class TestMainParser:
    """Tests for main CLI parser."""

    def test_help_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that --help displays usage information."""
        with patch.object(sys, "argv", ["wt-compiler", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "wt-compiler" in captured.out
        assert "compile" in captured.out

    def test_compile_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that compile --help displays compile-specific help."""
        with patch.object(sys, "argv", ["wt-compiler", "compile", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "--spec" in captured.out
        assert "--clobber" in captured.out
        assert "--update" in captured.out

    def test_no_command_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that missing command shows error."""
        with patch.object(sys, "argv", ["wt-compiler"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        # argparse exits with code 2 for argument errors
        assert exc_info.value.code == 2

    def test_compile_missing_spec_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that compile without --spec shows error."""
        with patch.object(sys, "argv", ["wt-compiler", "compile"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "--spec" in captured.err


class TestCompileCommand:
    """Tests for the compile command."""

    def test_spec_file_not_found(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test error when spec file doesn't exist."""
        with patch.object(
            sys, "argv", ["wt-compiler", "compile", "--spec", "/nonexistent/spec.yaml"]
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error: Spec file not found" in captured.err

    def test_spec_path_is_directory(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test error when spec path is a directory."""
        with patch.object(sys, "argv", ["wt-compiler", "compile", "--spec", str(tmp_path)]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error: Spec path is not a file" in captured.err

    def test_compile_success(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        """Test successful compilation with mocked compile_workflow_from_yaml."""
        # Create a dummy spec file
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text("id: test-workflow\n")

        # Create mock artifacts
        mock_artifacts = MagicMock()
        mock_artifacts.release_dir = tmp_path / "test-workflow"

        with patch.object(sys, "argv", ["wt-compiler", "compile", "--spec", str(spec_file)]):
            with patch(
                "wt_compiler.cli.compile_workflow_from_yaml", return_value=mock_artifacts
            ) as mock_compile:
                main()

        mock_compile.assert_called_once_with(
            str(spec_file.resolve()), progress=True, pkg_name_prefix="wt"
        )
        mock_artifacts.dump.assert_called_once_with(clobber=False, update=False)

        captured = capsys.readouterr()
        assert "Compiled workflow to:" in captured.out

    def test_compile_with_clobber(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        """Test compilation with --clobber flag."""
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text("id: test-workflow\n")

        mock_artifacts = MagicMock()
        mock_artifacts.release_dir = tmp_path / "test-workflow"

        with patch.object(
            sys, "argv", ["wt-compiler", "compile", "--spec", str(spec_file), "--clobber"]
        ):
            with patch("wt_compiler.cli.compile_workflow_from_yaml", return_value=mock_artifacts):
                main()

        mock_artifacts.dump.assert_called_once_with(clobber=True, update=False)

    def test_compile_with_update(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        """Test compilation with --update flag."""
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text("id: test-workflow\n")

        mock_artifacts = MagicMock()
        mock_artifacts.release_dir = tmp_path / "test-workflow"

        with patch.object(
            sys,
            "argv",
            ["wt-compiler", "compile", "--spec", str(spec_file), "--clobber", "--update"],
        ):
            with patch("wt_compiler.cli.compile_workflow_from_yaml", return_value=mock_artifacts):
                main()

        mock_artifacts.dump.assert_called_once_with(clobber=True, update=True)

    def test_compile_file_exists_error(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test error handling when output directory exists without --clobber."""
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text("id: test-workflow\n")

        mock_artifacts = MagicMock()
        mock_artifacts.dump.side_effect = FileExistsError("Path 'test-workflow' already exists.")

        with patch.object(sys, "argv", ["wt-compiler", "compile", "--spec", str(spec_file)]):
            with patch("wt_compiler.cli.compile_workflow_from_yaml", return_value=mock_artifacts):
                with pytest.raises(SystemExit) as exc_info:
                    main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err
        assert "--clobber" in captured.err

    def test_compile_general_error(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test error handling for general exceptions during compilation."""
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text("id: test-workflow\n")

        with patch.object(sys, "argv", ["wt-compiler", "compile", "--spec", str(spec_file)]):
            with patch(
                "wt_compiler.cli.compile_workflow_from_yaml",
                side_effect=ValueError("Invalid spec format"),
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error: Invalid spec format" in captured.err


class TestModuleEntryPoint:
    """Tests for python -m wt_compiler entry point."""

    def test_main_module_import(self) -> None:
        """Test that __main__.py can be imported."""
        import wt_compiler.__main__

        assert hasattr(wt_compiler.__main__, "main")

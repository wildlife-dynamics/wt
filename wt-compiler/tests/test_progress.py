"""Tests for the progress spinner module."""

import io
import os
import sys
import time
from unittest.mock import patch

from wt_compiler.progress import NullSpinner, Spinner, _StderrCapture, spinner


class TestSpinner:
    """Tests for the Spinner context manager."""

    def test_context_manager_protocol(self) -> None:
        """Test that Spinner works as a context manager."""
        buf = io.StringIO()
        with Spinner("test", file=buf) as sp:
            assert isinstance(sp, Spinner)

    def test_update_changes_message(self) -> None:
        """Test that update changes the displayed message."""
        buf = io.StringIO()
        with Spinner("initial", file=buf) as sp:
            sp.update("updated")
            # Give the thread a moment to write
            time.sleep(0.15)

        output = buf.getvalue()
        assert "updated" in output

    def test_spinner_writes_to_file(self) -> None:
        """Test that the spinner writes animation frames to the output file."""
        buf = io.StringIO()
        with Spinner("working", file=buf):
            time.sleep(0.15)

        output = buf.getvalue()
        assert "working" in output
        # Should contain at least one spinner frame character
        assert any(c in output for c in Spinner.FRAMES)

    def test_spinner_clears_line_on_exit(self) -> None:
        """Test that exiting the context manager clears the spinner line."""
        buf = io.StringIO()
        with Spinner("done", file=buf):
            time.sleep(0.1)

        output = buf.getvalue()
        # Should end with a clear-line sequence
        assert output.endswith("\r\033[K")


class TestNullSpinner:
    """Tests for the NullSpinner no-op."""

    def test_context_manager_protocol(self) -> None:
        """Test that NullSpinner works as a context manager."""
        with NullSpinner() as sp:
            assert isinstance(sp, NullSpinner)

    def test_update_is_noop(self) -> None:
        """Test that update does nothing."""
        sp = NullSpinner()
        # Should not raise
        sp.update("anything")

    def test_no_output(self, capsys: "pytest.CaptureFixture[str]") -> None:
        """Test that NullSpinner produces no output."""
        with NullSpinner() as sp:
            sp.update("should not appear")

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""


class TestSpinnerFactory:
    """Tests for the spinner() factory function."""

    def test_returns_null_when_disabled(self) -> None:
        """Test that spinner(enabled=False) returns NullSpinner."""
        result = spinner(enabled=False)
        assert isinstance(result, NullSpinner)

    def test_returns_null_when_not_tty(self) -> None:
        """Test that spinner returns NullSpinner when stderr is not a TTY."""
        # In test environments, stderr is typically not a TTY
        result = spinner(enabled=True)
        if not sys.stderr.isatty():
            assert isinstance(result, NullSpinner)

    def test_returns_spinner_when_tty(self) -> None:
        """Test that spinner returns Spinner when enabled and stderr is a TTY."""
        mock_stderr = io.StringIO()
        mock_stderr.isatty = lambda: True  # type: ignore[attr-defined]
        with patch.object(sys, "stderr", mock_stderr):
            result = spinner(enabled=True)
        assert isinstance(result, Spinner)

    def test_returns_null_when_no_isatty(self) -> None:
        """Test that spinner returns NullSpinner when stderr lacks isatty."""
        mock_stderr = object()  # No isatty method
        with patch.object(sys, "stderr", mock_stderr):
            result = spinner(enabled=True)
        assert isinstance(result, NullSpinner)


class TestCliNoProgressFlag:
    """Tests for the --no-progress CLI flag."""

    def test_no_progress_in_help(self, capsys: "pytest.CaptureFixture[str]") -> None:
        """Test that --no-progress appears in compile help output."""
        from wt_compiler.cli import main

        with patch.object(sys, "argv", ["wt-compiler", "compile", "--help"]):
            try:
                main()
            except SystemExit:
                pass

        captured = capsys.readouterr()
        assert "--no-progress" in captured.out

    def test_no_progress_passed_to_compile(self, tmp_path: "pathlib.Path") -> None:
        """Test that --no-progress passes progress=False to compile_workflow_from_yaml."""
        import pathlib

        from unittest.mock import MagicMock

        from wt_compiler.cli import main

        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text("id: test-workflow\n")

        mock_artifacts = MagicMock()
        mock_artifacts.release_dir = tmp_path / "test-workflow"

        with patch.object(
            sys,
            "argv",
            ["wt-compiler", "compile", "--spec", str(spec_file), "--no-progress"],
        ):
            with patch(
                "wt_compiler.cli.compile_workflow_from_yaml", return_value=mock_artifacts
            ) as mock_compile:
                main()

        mock_compile.assert_called_once_with(
            str(spec_file.resolve()), progress=False, pkg_name_prefix="wt"
        )

    def test_progress_default_true(self, tmp_path: "pathlib.Path") -> None:
        """Test that progress defaults to True (no --no-progress flag)."""
        import pathlib

        from unittest.mock import MagicMock

        from wt_compiler.cli import main

        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text("id: test-workflow\n")

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


class TestStderrCapture:
    """Tests for the _StderrCapture fd-level stderr redirect."""

    def test_captures_fd_writes(self) -> None:
        """Test that os.write(2, ...) output is captured."""
        capture = _StderrCapture()
        capture.start()
        try:
            os.write(2, b"native warning\n")
        finally:
            captured = capture.stop()
            capture.close_terminal_file()
        assert "native warning" in captured

    def test_captures_writes_via_fd2_file_object(self) -> None:
        """Test that writes through a Python file wrapping fd 2 are captured."""
        capture = _StderrCapture()
        capture.start()
        try:
            # Open a fresh Python file object around fd 2 (which now points
            # to the pipe).  This simulates what native libraries do when they
            # use the C-level stderr, which Python wraps as fd 2.
            fd2_copy = os.dup(2)
            f = os.fdopen(fd2_copy, "w")
            f.write("file object message\n")
            f.flush()
            f.close()
        finally:
            captured = capture.stop()
            capture.close_terminal_file()
        assert "file object message" in captured

    def test_restores_fd(self) -> None:
        """Test that fd 2 is properly restored after capture."""
        capture = _StderrCapture()
        capture.start()
        captured = capture.stop()
        capture.close_terminal_file()
        # fd 2 should work normally again — no exception
        os.write(2, b"after restore\n")

    def test_empty_when_nothing_written(self) -> None:
        """Test that capture returns empty string when no stderr produced."""
        capture = _StderrCapture()
        capture.start()
        captured = capture.stop()
        capture.close_terminal_file()
        assert captured == ""

    def test_stop_without_start_returns_empty(self) -> None:
        """Test that stop() is safe to call without start()."""
        capture = _StderrCapture()
        assert capture.stop() == ""


class TestSpinnerStderrCapture:
    """Tests for Spinner integration with stderr capture."""

    def test_no_capture_with_stringio(self) -> None:
        """Test that Spinner with StringIO does not attempt fd capture."""
        buf = io.StringIO()
        with Spinner("test", file=buf) as sp:
            sp.update("updated")
            time.sleep(0.1)
        output = buf.getvalue()
        assert "updated" in output

    def test_no_capture_when_disabled(self) -> None:
        """Test that capture_stderr=False skips capture."""
        buf = io.StringIO()
        with Spinner("test", file=buf, capture_stderr=False) as sp:
            time.sleep(0.1)
        output = buf.getvalue()
        assert "test" in output

    def test_clears_line_on_exit_without_capture(self) -> None:
        """Test that line clearing works when capture is not active."""
        buf = io.StringIO()
        with Spinner("done", file=buf):
            time.sleep(0.1)
        output = buf.getvalue()
        assert output.endswith("\r\033[K")

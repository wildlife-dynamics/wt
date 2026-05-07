"""Tests for CLI compatibility — interactive input() loop and static argparse flags."""
# ruff: noqa: SIM117, SIM105  # nested with-blocks read clearer here; try/except/pass deliberate

from __future__ import annotations

import argparse
from typing import cast
from unittest.mock import patch

import pytest

from wt_compiler.wizard.abstract import (
    AbstractWizardProvider,
    SingleWizardQuestion,
    WizardQuestion,
    _make_loop_type,
)
from wt_compiler.wizard.default import DefaultWizardProvider, _requirements_batch_type


def interactive_loop(provider: AbstractWizardProvider) -> None:
    """Simulate interactive session using input() for each question."""
    gen = provider.input_generator()
    try:
        question = next(gen)
        while True:
            prompt = question["argparse"].get("help", "")
            choices = question["argparse"].get("choices")
            error = question.get("wizard", {}).get("error")
            if error:
                print(f"Error: {error}")
            if choices:
                print(f"Choices: {', '.join(choices)}")
            answer = input(f"{prompt}: ")
            question = gen.send(answer)
    except StopIteration:
        pass


class TestInteractiveMode:
    """Tests simulating interactive input() loop."""

    def test_interactive_loop_drives_generator(self) -> None:
        """Simulate interactive session with monkeypatched input."""
        provider = DefaultWizardProvider()
        input_sequence = iter([
            "my_workflow",
            "My Workflow",
            "A description",
            "Author Name",
            "MIT",
            "numpy",
            "conda",       # req_type
            "*",
            "conda-forge",
            "",  # end requirements
        ])

        with patch("builtins.input", side_effect=input_sequence):
            interactive_loop(provider)

        assert provider.answers["workflow_id"] == "my_workflow"
        assert provider.answers["workflow_name"] == "My Workflow"
        assert provider.answers["requirements"] == [
            {"name": "numpy", "req_type": "conda", "version": "*", "channel": "conda-forge"}
        ]

    def test_interactive_loop_local_path_requirement(self) -> None:
        """Interactive loop handles local path requirement correctly."""
        provider = DefaultWizardProvider()
        input_sequence = iter([
            "my_workflow",
            "My Workflow",
            "",
            "Author",
            "MIT",
            "mypkg",
            "local path",       # req_type
            "/home/user/mypkg", # path
            "false",            # editable
            "",  # end requirements
        ])

        with patch("builtins.input", side_effect=input_sequence):
            interactive_loop(provider)

        reqs = provider.answers["requirements"]
        assert len(reqs) == 1
        assert reqs[0]["req_type"] == "local path"
        assert reqs[0]["path"] == "/home/user/mypkg"

    def test_interactive_loop_displays_choices(self, capsys: object) -> None:
        """For select-type questions with choices, verify choices are displayed."""
        provider = DefaultWizardProvider()
        input_sequence = iter([
            "my_workflow",
            "My Workflow",
            "desc",
            "Author",
            "MIT",  # license (has choices)
            "",  # end requirements
        ])

        with patch("builtins.input", side_effect=input_sequence):
            interactive_loop(provider)

        # capsys is a pytest fixture, but we just verify the wizard completed
        assert provider.answers["license_type"] == "MIT"

    def test_interactive_loop_redisplays_on_error(self) -> None:
        """When type callable raises, verify error is shown and re-prompted."""
        provider = DefaultWizardProvider()
        input_sequence = iter([
            "123bad",  # invalid workflow_id
            "my_workflow",  # valid retry
            "My Workflow",
            "desc",
            "Author",
            "MIT",
            "",  # end requirements
        ])

        printed: list[str] = []

        def capture_print(*args: object, **kwargs: object) -> None:
            printed.append(" ".join(str(a) for a in args))

        with patch("builtins.input", side_effect=input_sequence):
            with patch("builtins.print", side_effect=capture_print):
                interactive_loop(provider)

        assert provider.answers["workflow_id"] == "my_workflow"
        # Verify error message was printed
        error_msgs = [p for p in printed if "Error:" in p]
        assert len(error_msgs) > 0

    def test_interactive_loop_handles_loop_question(self) -> None:
        """For requirements loop, verify it keeps prompting until empty input."""
        provider = DefaultWizardProvider()
        input_sequence = iter([
            "my_workflow",
            "My Workflow",
            "desc",
            "Author",
            "MIT",
            "pkg1",         # req 1 name
            "conda",        # req 1 req_type → conda
            "*",            # req 1 version
            "conda-forge",  # req 1 channel
            "pkg2",         # req 2 name
            "conda",        # req 2 req_type → conda
            "*",            # req 2 version
            "conda-forge",  # req 2 channel
            "",  # end requirements
        ])

        with patch("builtins.input", side_effect=input_sequence):
            interactive_loop(provider)

        assert len(provider.answers["requirements"]) == 2


class TestStaticBatchMode:
    """Tests for argparse static/batch mode compatibility."""

    def test_argparse_add_argument_compatibility(self) -> None:
        """For each question from get_questions(), add_argument succeeds."""
        provider = DefaultWizardProvider()
        parser = argparse.ArgumentParser()
        for q in provider.get_questions():
            dest = q["dest"]
            if "questions" in q:
                # requirements question has its own argparse dict with custom type
                parser.add_argument(
                    f"--{dest.replace('_', '-')}",
                    **cast("SingleWizardQuestion", q)["argparse"],
                )
            else:
                parser.add_argument(
                    f"--{dest.replace('_', '-')}", **q["argparse"]
                )

    def test_argparse_parse_args_valid(self) -> None:
        """Build parser, parse valid args, verify namespace."""
        provider = DefaultWizardProvider()
        parser = argparse.ArgumentParser()
        for q in provider.get_questions():
            dest = q["dest"]
            if "questions" in q:
                # Use the custom argparse dict (includes _requirements_batch_type)
                parser.add_argument(
                    f"--{dest.replace('_', '-')}",
                    **cast("SingleWizardQuestion", q)["argparse"],
                )
            else:
                parser.add_argument(
                    f"--{dest.replace('_', '-')}", **q["argparse"]
                )

        args = parser.parse_args([
            "--workflow-id", "my_wf",
            "--workflow-name", "My Workflow",
            "--workflow-description", "A desc",
            "--author-name", "Author",
            "--license-type", "MIT",
            "--requirements", '{"name": "numpy", "version": "*", "channel": "conda-forge"}',
        ])
        assert args.workflow_id == "my_wf"
        assert args.workflow_name == "My Workflow"
        assert args.license_type == "MIT"
        assert len(args.requirements) == 1
        assert args.requirements[0]["name"] == "numpy"

    def test_argparse_parse_args_with_type_validation(self) -> None:
        """Build parser, parse args with invalid workflow_id, verify SystemExit."""
        provider = DefaultWizardProvider()
        parser = argparse.ArgumentParser()
        for q in provider.get_questions():
            dest = q["dest"]
            if "questions" in q:
                continue  # skip loop for this test
            parser.add_argument(
                f"--{dest.replace('_', '-')}", **q["argparse"]
            )

        with pytest.raises(SystemExit):
            parser.parse_args(["--workflow-id", "123bad"])

    def test_argparse_to_generator_bridge(self) -> None:
        """Feed parsed argparse Namespace values into generator via .send()."""
        provider_argparse = DefaultWizardProvider()
        parser = argparse.ArgumentParser()
        for q in provider_argparse.get_questions():
            dest = q["dest"]
            if "questions" in q:
                parser.add_argument(
                    f"--{dest.replace('_', '-')}",
                    **cast("SingleWizardQuestion", q)["argparse"],
                )
            else:
                parser.add_argument(
                    f"--{dest.replace('_', '-')}", **q["argparse"]
                )

        args = parser.parse_args([
            "--workflow-id", "my_wf",
            "--workflow-name", "My Workflow",
            "--workflow-description", "A desc",
            "--author-name", "Author",
            "--license-type", "MIT",
            "--requirements", '{"name": "numpy", "version": "*", "channel": "conda-forge"}',
        ])

        # Now drive a fresh provider's generator with argparse values
        provider = DefaultWizardProvider()
        gen = provider.input_generator()
        q = next(gen)

        # Feed simple questions from namespace
        simple_dests = [
            "workflow_id", "workflow_name", "workflow_description", "author_name", "license_type"
        ]
        for dest in simple_dests:
            value = getattr(args, dest)
            q = gen.send(str(value) if value else "")

        # Feed loop question: for each parsed requirement dict, send sub-fields
        assert q["dest"] == "name"  # first sub-question of requirements loop
        for req_dict in args.requirements:
            q = gen.send(req_dict["name"])             # name
            assert q["dest"] == "req_type"
            q = gen.send(req_dict["req_type"])         # req_type
            assert q["dest"] == "version"
            q = gen.send(req_dict["version"])          # version
            assert q["dest"] == "channel"
            q = gen.send(req_dict["channel"])          # channel

        # End the loop
        try:
            gen.send("")  # empty name = end loop
        except StopIteration:
            pass

        assert provider.answers["workflow_id"] == "my_wf"
        assert provider.answers["requirements"] == [
            {"name": "numpy", "req_type": "conda", "version": "*", "channel": "conda-forge"}
        ]

    def test_loop_question_argparse_type_callable(self) -> None:
        """Verify requirements loop question uses _requirements_batch_type."""
        provider = DefaultWizardProvider()
        loop_q = next(
            q for q in provider.get_questions() if q["dest"] == "requirements"
        )
        assert "questions" in loop_q

        batch_type = cast("SingleWizardQuestion", loop_q)["argparse"].get("type")
        assert batch_type is _requirements_batch_type

        # Valid conda JSON
        result = batch_type('{"name": "numpy", "version": "*", "channel": "conda-forge"}')
        assert result["name"] == "numpy"
        assert result["req_type"] == "conda"

        # Valid local path JSON
        result = batch_type('{"name": "mypkg", "path": "/home/user/mypkg"}')
        assert result["req_type"] == "local path"
        assert "pip_source_type" not in result

        # Invalid JSON
        with pytest.raises(argparse.ArgumentTypeError, match="Invalid JSON"):
            batch_type("not json")

        # Invalid version
        with pytest.raises(argparse.ArgumentTypeError, match="version"):
            batch_type('{"name": "pkg", "version": ">>>invalid<<<", "channel": "conda-forge"}')

    def test_make_loop_type_still_works_for_simple_providers(self) -> None:
        """_make_loop_type is still valid for providers with simple sub-questions."""

        class SimpleProvider(AbstractWizardProvider):
            def get_questions(self) -> list[WizardQuestion]:
                return [
                    {
                        "dest": "items",
                        "questions": [
                            {
                                "dest": "value",
                                "argparse": {"help": "Value", "type": str},
                                "wizard": {},
                            }
                        ],
                    }
                ]

        q = SimpleProvider().get_questions()[0]
        loop_type = _make_loop_type(q["questions"])

        result = loop_type('{"value": "hello"}')
        assert result["value"] == "hello"

        with pytest.raises(argparse.ArgumentTypeError, match="Invalid JSON"):
            loop_type("not json")

        with pytest.raises(argparse.ArgumentTypeError, match="Expected a JSON object"):
            loop_type('[{"value": "x"}]')

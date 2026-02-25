"""Tests for AbstractWizardProvider ABC conformance and generator mechanics."""

from __future__ import annotations

import argparse

from conftest import drive_wizard

from wt_compiler.wizard.abstract import AbstractWizardProvider, SingleWizardQuestion
from wt_compiler.wizard.default import DefaultWizardProvider


class TestABCConformance:
    """Tests for ABC conformance."""

    def test_default_provider_is_subclass(self) -> None:
        """DefaultWizardProvider is a subclass of AbstractWizardProvider."""
        assert issubclass(DefaultWizardProvider, AbstractWizardProvider)

    def test_abstract_methods_enforced(self) -> None:
        """Attempting to instantiate AbstractWizardProvider directly raises TypeError."""
        try:
            AbstractWizardProvider()  # type: ignore[abstract]
            assert False, "Expected TypeError"
        except TypeError:
            pass


class TestGeneratorMechanics:
    """Tests for generator protocol mechanics."""

    def test_input_generator_yields_dicts_with_required_keys(self) -> None:
        """Every yielded dict has 'dest' (str) and 'argparse' (dict with 'help')."""
        provider = DefaultWizardProvider()
        gen = provider.input_generator()
        q = next(gen)
        assert isinstance(q["dest"], str)
        assert isinstance(q["argparse"], dict)
        assert "help" in q["argparse"]

    def test_argparse_compatibility(self) -> None:
        """For each yielded question, argparse kwargs can be passed to add_argument."""
        provider = DefaultWizardProvider()
        gen = provider.input_generator()
        # Collect all questions by driving through with valid answers
        valid_answers = [
            "my_workflow",  # workflow_id
            "My Workflow",  # workflow_name
            "A description",  # workflow_description
            "Author Name",  # author_name
            "MIT",  # license_type
            "numpy",  # requirements[0].name
            "*",  # requirements[0].version
            "conda-forge",  # requirements[0].channel
            "",  # end requirements loop
        ]
        questions = drive_wizard(provider, valid_answers)

        parser = argparse.ArgumentParser()
        seen_dests: set[str] = set()
        for q in questions:
            dest = q["dest"]
            if dest in seen_dests:
                continue
            seen_dests.add(dest)
            parser.add_argument(
                f"--{dest.replace('_', '-')}", **q["argparse"]
            )

    def test_send_based_flow_complete(self) -> None:
        """Drive generator with valid answers, verify StopIteration and answers populated."""
        provider = DefaultWizardProvider()
        valid_answers = [
            "my_workflow",  # workflow_id
            "My Workflow",  # workflow_name
            "A description",  # workflow_description
            "Author Name",  # author_name
            "MIT",  # license_type
            "numpy",  # requirements[0].name
            "*",  # requirements[0].version
            "conda-forge",  # requirements[0].channel
            "",  # end requirements loop
        ]
        drive_wizard(provider, valid_answers)

        assert provider.answers["workflow_id"] == "my_workflow"
        assert provider.answers["workflow_name"] == "My Workflow"
        assert provider.answers["workflow_description"] == "A description"
        assert provider.answers["author_name"] == "Author Name"
        assert provider.answers["license_type"] == "MIT"
        assert provider.answers["requirements"] == [
            {"name": "numpy", "version": "*", "channel": "conda-forge"}
        ]

    def test_invalid_answer_reyields_with_error(self) -> None:
        """Send invalid workflow_id, verify re-yielded dict has wizard.error set."""
        provider = DefaultWizardProvider()
        gen = provider.input_generator()
        q = next(gen)
        assert q["dest"] == "workflow_id"

        # Send invalid value (not an identifier)
        q2 = gen.send("123bad")
        assert q2["dest"] == "workflow_id"
        assert "error" in q2["wizard"]
        assert q2["wizard"]["error"]  # non-empty error message

"""Shared test fixtures and helpers for wt-compiler tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from wt_compiler.compiler import _load_default_injections, compute_merged_default_feature

if TYPE_CHECKING:
    from wt_compiler.pixi_toml_fragment import FeatureSection
    from wt_compiler.wizard.abstract import AbstractWizardProvider


@pytest.fixture
def merged_default_feature() -> FeatureSection:
    """Merged default feature with no env-overrides and no spec-supplied suppressions.

    Equivalent to what ``compile_workflow_from_yaml`` produces for a
    spec whose ``requirements:`` list has no overlap with the bundled
    ``default-env-injections.toml`` baseline. Pass this to
    :meth:`DagCompiler.compile` / :meth:`DagCompiler.get_pixi_toml` in
    test sites that don't explicitly exercise the env-overrides or
    spec-supplied-suppression paths.
    """
    return compute_merged_default_feature(
        _load_default_injections(),
        spec_supplied_names=set(),
    )


def drive_wizard(provider: AbstractWizardProvider, answers: list[str | None]) -> list[dict]:
    """Drive wizard generator with a sequence of answers. Returns all yielded questions."""
    gen = provider.input_generator()
    questions: list[dict] = []
    try:
        q = next(gen)
        questions.append(q)
        for ans in answers:
            q = gen.send(ans)
            questions.append(q)
    except StopIteration:
        pass
    return questions

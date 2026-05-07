"""Shared test fixtures and helpers for wizard tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wt_compiler.wizard.abstract import AbstractWizardProvider


def drive_wizard(
    provider: AbstractWizardProvider, answers: list[str | None]
) -> list[dict]:
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

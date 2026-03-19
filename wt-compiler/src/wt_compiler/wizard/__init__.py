"""Wizard provider framework for interactive workflow project scaffolding.

Re-exports the ``AbstractWizardProvider`` ABC, ``DefaultWizardProvider``
reference implementation, and all supporting TypedDict types.
"""

from wt_compiler.wizard.abstract import (
    AbstractWizardProvider,
    ArgparseKwargs,
    LoopContext,
    SingleWizardQuestion,
    WizardKwargs,
    WizardQuestion,
    WizardQuestionLoop,
    with_condition,
)
from wt_compiler.wizard.default import DefaultWizardProvider

__all__ = [
    "AbstractWizardProvider",
    "ArgparseKwargs",
    "DefaultWizardProvider",
    "LoopContext",
    "SingleWizardQuestion",
    "WizardKwargs",
    "WizardQuestion",
    "WizardQuestionLoop",
    "with_condition",
]

"""Example custom wizard provider — test fixture for wt-compiler.

Registered as the ``example`` entry point in the ``wt_compiler.wizard_providers``
group (declared in the fixture package's ``pyproject.toml``).

Install for testing::

    uv pip install -e tests/fixtures/example-provider/

Examples:
    >>> from wt_example_provider import ExampleProvider
    >>> p = ExampleProvider()
    >>> [q["dest"] for q in p.get_questions()]
    ['workflow_id', 'project_type']
"""

from __future__ import annotations

from wt_compiler.wizard.abstract import AbstractWizardProvider, WizardQuestion
from wt_compiler.wizard.default import workflow_id_type


class ExampleProvider(AbstractWizardProvider):
    """Minimal custom provider with two questions.

    Asks for a ``workflow_id`` (required by the CLI to name the output
    directory) and a ``project_type`` chosen from a fixed list.  Intended
    as both a test fixture and a concise reference for third-party provider
    authors.

    Examples:
        >>> p = ExampleProvider()
        >>> gen = p.input_generator()
        >>> q = next(gen)
        >>> q["dest"]
        'workflow_id'
        >>> q = gen.send("my_workflow")
        >>> q["dest"]
        'project_type'
        >>> try:
        ...     gen.send("batch")
        ... except StopIteration:
        ...     pass
        >>> p.answers["workflow_id"]
        'my_workflow'
        >>> p.answers["project_type"]
        'batch'
    """

    def get_questions(self) -> list[WizardQuestion]:
        """Return the two questions this provider asks.

        Returns:
            A list containing a ``workflow_id`` text question and a
            ``project_type`` select question.
        """
        return [
            {
                "dest": "workflow_id",
                "argparse": {
                    "type": workflow_id_type,
                    "help": "Workflow ID (valid Python identifier, ≤64 chars)",
                },
                "wizard": {},
            },
            {
                "dest": "project_type",
                "argparse": {
                    "choices": ["batch", "streaming", "interactive"],
                    "default": "batch",
                    "help": "Project execution model",
                },
                "wizard": {},
            },
        ]

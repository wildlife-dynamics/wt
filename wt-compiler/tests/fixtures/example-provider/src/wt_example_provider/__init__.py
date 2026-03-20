"""Example custom wizard provider — test fixture for wt-compiler.

Extends ``DefaultWizardProvider`` with one additional question
(``add_boilerplate_tasks``) and overrides ``spec.yaml.jinja2`` to inject
example tasks into the generated spec when requested.

Registered as the ``example`` entry point in the ``wt_compiler.wizard_providers``
group (declared in the fixture package's ``pyproject.toml``).

Install for testing::

    uv pip install -e tests/fixtures/example-provider/

Examples:
    >>> from wt_example_provider import ExampleProvider
    >>> p = ExampleProvider()
    >>> p.get_questions()[-1]["dest"]
    'add_boilerplate_tasks'
"""

from __future__ import annotations

from wt_compiler.wizard.default import DefaultWizardProvider
from wt_compiler.wizard.abstract import WizardQuestion


class ExampleProvider(DefaultWizardProvider):
    """DefaultWizardProvider extended with an ``add_boilerplate_tasks`` question.

    Asks all standard questions from ``DefaultWizardProvider``, then asks
    whether to populate ``spec.yaml`` with example boilerplate tasks.
    The bundled ``spec.yaml.jinja2`` template overrides the default one and
    renders the tasks section conditionally.

    Examples:
        >>> p = ExampleProvider()
        >>> questions = p.get_questions()
        >>> questions[-1]["dest"]
        'add_boilerplate_tasks'
        >>> questions[-1]["argparse"]["choices"]
        ['yes', 'no']
    """

    def get_questions(self) -> list[WizardQuestion]:
        """Return default questions plus ``add_boilerplate_tasks``.

        Returns:
            All questions from ``DefaultWizardProvider`` followed by the
            ``add_boilerplate_tasks`` select question.
        """
        return [
            *super().get_questions(),
            {
                "dest": "add_boilerplate_tasks",
                "argparse": {
                    "choices": ["yes", "no"],
                    "default": "yes",
                    "help": "Populate spec.yaml with example boilerplate tasks",
                },
                "wizard": {},
            },
        ]

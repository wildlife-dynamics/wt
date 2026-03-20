"""ExampleProvider — concrete wizard provider implementation."""

from wt_compiler.wizard.abstract import WizardQuestion
from wt_compiler.wizard.default import DefaultWizardProvider


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

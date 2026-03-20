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

from wt_example_provider.example_provider import ExampleProvider

__all__ = ["ExampleProvider"]

# Changelog

## v0.2.0 — 2026-05-13

- Add `formdata` module: schema-driven conversion helpers `formdata_to_params` / `params_to_formdata`, a `validate` wrapper around `jsonschema.Draft202012Validator`, and `ValidationError` / `ValidationErrorResponse` / `ValidationErrorItem` Pydantic models for FastAPI/OpenAPI use ([#164](https://github.com/wildlife-dynamics/wt/pull/164))
- Add `jsonschema>=4.0.0,<5.0.0` runtime dependency ([#164](https://github.com/wildlife-dynamics/wt/pull/164))
- Standardize ruff lint config to enforce type annotations and Google-style docstrings ([#155](https://github.com/wildlife-dynamics/wt/pull/155))

## v0.1.2 — 2026-03-13

- Bootstrap release for prefix.dev conda channel

## v0.1.1 — 2026-03-05

- Fix incorrect license metadata

## v0.1.0 — 2026-03-05

- Initial release

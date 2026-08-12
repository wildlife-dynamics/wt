"""Base Pydantic model classes with specific configurations."""

from pydantic import BaseModel, ConfigDict

__all__ = [
    "_AllowArbitraryAndForbidExtra",
    "_AllowArbitraryAndValidateAssignment",
    "_AllowArbitraryTypes",
    "_AllowExtra",
    "_ForbidExtra",
    "_ValidateAssignment",
]


class _AllowArbitraryTypes(BaseModel):
    """Base model that allows arbitrary types."""

    model_config = ConfigDict(arbitrary_types_allowed=True)


class _AllowArbitraryAndValidateAssignment(BaseModel):
    """Base model that allows arbitrary types and validates on assignment."""

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)


class _AllowArbitraryAndForbidExtra(BaseModel):
    """Base model that allows arbitrary types and forbids extra fields."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")


class _AllowExtra(BaseModel):
    """Base model that allows (and retains) extra fields."""

    model_config = ConfigDict(extra="allow")


class _ForbidExtra(BaseModel):
    """Base model that forbids extra fields."""

    model_config = ConfigDict(extra="forbid")


class _ValidateAssignment(BaseModel):
    """Base model that validates on assignment."""

    model_config = ConfigDict(validate_assignment=True)

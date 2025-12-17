"""wt-registry: Explicit function registry with JSON schema generation."""

from wt_registry.decorator import register
from wt_registry.registry import get_registry

__all__ = ["get_registry", "register"]

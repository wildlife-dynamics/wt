"""wt-compiler-service: a hot-registry, on-the-fly workflow compile server.

The FastAPI application lives at :data:`wt_compiler_service.app.app` (module
``app``, instance ``app``) and is served as ``wt_compiler_service.app:app``.
The application object is intentionally *not* re-exported here, so the ``app``
submodule is not shadowed by the instance.
"""

try:
    from wt_compiler_service._version import __version__
except ImportError:
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]

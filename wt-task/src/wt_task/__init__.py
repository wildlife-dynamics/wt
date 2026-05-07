"""Task decorator and execution features for wt ecosystem.

This package provides the @task decorator and task execution capabilities
for workflow systems. It implements the TaskProtocol from wt-contracts.
"""

from .async_task import AsyncTask
from .decorator import Task, task
from .exceptions import TaskInstanceError, handle_errors
from .executors import (
    AsyncExecutor,
    Future,
    FutureSequence,
    PythonExecutor,
    SyncExecutor,
)
from .skip import (
    SKIP_SENTINEL,
    SkippedDependencyFallback,
    SkipSentinel,
    skipif,
    unpack_listlike,
)
from .sync_task import SyncTask

__all__ = [
    "SKIP_SENTINEL",
    "AsyncExecutor",
    "AsyncTask",
    "Future",
    "FutureSequence",
    "PythonExecutor",
    # Skip utilities
    "SkipSentinel",
    "SkippedDependencyFallback",
    # Executors
    "SyncExecutor",
    "SyncTask",
    "Task",
    # Exceptions
    "TaskInstanceError",
    "handle_errors",
    "skipif",
    # Main decorator and task types
    "task",
    "unpack_listlike",
]

# Version will be set by setuptools-scm
try:
    from ._version import __version__, __version_tuple__
except ImportError:
    __version__ = "0.0.0.dev0"
    __version_tuple__ = (0, 0, 0, "dev0")

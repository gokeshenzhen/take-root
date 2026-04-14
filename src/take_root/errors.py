from __future__ import annotations


class TakeRootError(Exception):
    """Base exception for take-root."""


class ConfigError(TakeRootError):
    """Invalid configuration or persona definition."""


class RuntimeCallError(TakeRootError):
    """Runtime invocation failed."""


class ArtifactError(TakeRootError):
    """Artifact file missing or malformed."""


class StateError(TakeRootError):
    """State file missing or inconsistent."""


class VCSError(TakeRootError):
    """VCS operation failed."""


class UserAbort(TakeRootError):
    """User aborted the workflow."""

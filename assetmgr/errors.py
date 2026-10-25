"""Shared error types for the Asset-Manager plug-in host."""


class ServerRequiredError(RuntimeError):
    """Raised when an operation needs the vendor sync server.

    Locking, channel notifications, membership management and other
    collaboration features are server-backed by design. Local git
    workflows work fully offline; only these methods raise.
    """


class DependencyMissingError(RuntimeError):
    """Raised when an optional external tool (ffmpeg, git, ...) is absent."""

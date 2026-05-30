"""Playbook module exceptions.

The router translates these into HTTPException via ``status_code`` so
callers see stable error semantics regardless of which DB or validation
path raised.
"""

from __future__ import annotations


class PlaybookError(Exception):
    """Base class for any playbook-related failure."""

    status_code: int = 500

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class PlaybookNotFoundError(PlaybookError):
    status_code = 404


class PlaybookValidationError(PlaybookError):
    status_code = 400


class PlaybookConflictError(PlaybookError):
    """Name already taken in the org, or invalid status transition."""

    status_code = 409


class PlaybookPermissionError(PlaybookError):
    """The caller's tenant does not own this playbook."""

    status_code = 403

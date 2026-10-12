"""Typed failures. Every job failure carries a stable `code` the UI can show and act on.

`retryable` decides the worker's behaviour: transient errors back off and retry,
permanent ones fail the job on the first attempt. Nothing is swallowed.
"""

from __future__ import annotations


class EditorError(Exception):
    code = "internal"
    retryable = False
    http_status = 500

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


class ProviderError(EditorError):
    """Gnani/Gemini call failed (network, 429, 5xx). Retried."""
    code = "provider_unavailable"
    retryable = True
    http_status = 502


class ProviderRejected(EditorError):
    """The provider refused the input (4xx other than 429). Not retried."""
    code = "provider_rejected"
    http_status = 422


class OutputInvalid(EditorError):
    """A model returned output that failed validation (e.g. chunks that rewrite the text)."""
    code = "output_invalid"
    retryable = True     # one more model call may produce valid output
    http_status = 502


class MediaFailed(EditorError):
    code = "media_failed"
    http_status = 422


class InputInvalid(EditorError):
    code = "input_invalid"
    http_status = 422


class NotFound(EditorError):
    code = "not_found"
    http_status = 404


class Conflict(EditorError):
    code = "conflict"
    http_status = 409


class Skip(Exception):
    """Job became irrelevant (stale chunk revision, deleted project). Recorded as SKIPPED."""


class StorageUnavailable(ProviderError):
    """Supabase Storage read/write failed. Retried."""
    code = "storage_unavailable"

"""LexiAfrik SDK — Exceptions."""

from typing import Optional


class LexiAfrikError(Exception):
    """Base error of the LexiAfrik SDK.

    ``detail`` holds the text returned by the server, when there is one. Its language is the
    server's: use it for logs, and show ``message`` (always English) to people.
    """

    def __init__(self, message: str = "", detail: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        if self.detail and self.detail not in self.message:
            return f"{self.message} [server: {self.detail}]"
        return self.message


class AuthenticationError(LexiAfrikError):
    """Invalid or revoked API key, or suspended account (HTTP 401 / 403)."""


class QuotaExceededError(LexiAfrikError):
    """Monthly quota and credit exhausted (HTTP 402): top up or change plan."""


class RateLimitError(LexiAfrikError):
    """Too many requests or attempts (HTTP 429)."""


class NotFoundError(LexiAfrikError):
    """Transcription, task or key not found (HTTP 404)."""


class AudioTooLargeError(LexiAfrikError):
    """File too large for this route (HTTP 413): use transcribe_large()."""


class UnsupportedFormatError(LexiAfrikError):
    """Unsupported audio format (HTTP 415)."""


class TranscriptionError(LexiAfrikError):
    """Transcription failed: unknown language, unreadable audio, failed job (HTTP 422)."""


class APIError(LexiAfrikError):
    """Generic API error (HTTP 5xx or unexpected)."""

    def __init__(self, message: str, status_code: Optional[int] = None, detail: Optional[str] = None):
        super().__init__(message, detail)
        self.status_code = status_code

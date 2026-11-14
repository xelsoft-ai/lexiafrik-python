"""LexiAfrik SDK — shared HTTP helpers: error mapping and automatic retries (used by both clients)."""

import random
from typing import Optional

import httpx

from .exceptions import (
    APIError, AudioTooLargeError, AuthenticationError, NotFoundError, QuotaExceededError,
    RateLimitError, TranscriptionError, UnsupportedFormatError,
)

#: Methods that can be repeated without side effects: also retried after a timeout or a gateway error.
IDEMPOTENT = frozenset({"GET", "HEAD", "DELETE", "PUT", "OPTIONS"})
#: Statuses where the server did not process the request: any method may be retried.
ALWAYS_RETRY_STATUS = frozenset({429, 503})
#: Statuses that may have been processed: only idempotent methods are retried.
IDEMPOTENT_RETRY_STATUS = frozenset({500, 502, 504})


class RetryPolicy:
    """Automatic retries with exponential backoff.

    Args:
        max_retries: number of retries after the first attempt (0 disables retries).
        backoff:     base delay in seconds (doubles each retry, with a little jitter).
        max_delay:   upper bound of a single wait, in seconds (also caps a server ``Retry-After``).

    A ``POST`` that creates something (transcription, key, payment) is never repeated after a timeout or a
    gateway error, because it may already have been processed and billed. It is repeated on 429 and 503 (not
    processed) and on connection errors (never sent).
    """

    def __init__(self, max_retries: int = 3, backoff: float = 0.5, max_delay: float = 30.0):
        self.max_retries = max(0, int(max_retries))
        self.backoff = backoff
        self.max_delay = max_delay

    def retry_status(self, method: str, status: int) -> bool:
        if status in ALWAYS_RETRY_STATUS:
            return True
        return status in IDEMPOTENT_RETRY_STATUS and method.upper() in IDEMPOTENT

    def retry_exception(self, method: str, exc: BaseException) -> bool:
        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
            return True  # the request never left: safe for every method
        if isinstance(exc, (httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)):
            return method.upper() in IDEMPOTENT
        return False

    def delay(self, attempt: int, response: Optional[httpx.Response] = None) -> float:
        """Wait before retry number ``attempt`` (1-based). Honors ``Retry-After`` (seconds) when present."""
        if response is not None:
            try:
                ra = float(response.headers.get("Retry-After", ""))
                return min(max(ra, 0.0), self.max_delay)
            except ValueError:
                pass
        return min(self.backoff * (2 ** (attempt - 1)) * (0.75 + random.random() * 0.5), self.max_delay)


def raise_for_response(response: httpx.Response) -> dict:
    """Turn a successful response into a dict, or raise the exception matching the status.

    The message is always English; the server's own text (its language is the server's) is kept in the
    exception's ``detail`` attribute and shown after the message."""
    if response.status_code < 300:
        return response.json() if response.content else {}

    try:
        body = response.json()
        detail = body.get("detail") or body.get("error") or response.text
    except Exception:
        detail = response.text
    if isinstance(detail, list):  # validation error (422)
        detail = "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)

    code = response.status_code
    detail = str(detail) if detail else None
    if code == 401:
        raise AuthenticationError("Invalid or revoked API key. Run `lexiafrik login` or check LEXIAFRIK_API_KEY.", detail)
    if code == 403:
        raise AuthenticationError("Access denied for this key or account.", detail)
    if code == 402:
        raise QuotaExceededError("Monthly quota and credit exhausted: top up or change plan.", detail)
    if code == 404:
        raise NotFoundError("Not found.", detail)
    if code == 413:
        raise AudioTooLargeError("File too large for this route: use transcribe_large().", detail)
    if code == 415:
        raise UnsupportedFormatError("Unsupported audio format.", detail)
    if code == 422:
        raise TranscriptionError("The request could not be processed.", detail)
    if code == 429:
        raise RateLimitError("Too many requests: slow down and retry shortly.", detail)
    raise APIError(f"API error (HTTP {code}).", status_code=code, detail=detail)

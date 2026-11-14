"""
LexiAfrik SDK — speech-to-text for Wolof and other African languages

Quick start:
    from lexiafrik import LexiAfrikClient

    client = LexiAfrikClient()          # key: api_key=, LEXIAFRIK_API_KEY or `lexiafrik login`
    result = client.transcribe("audio.wav", language="wo")
    print(result.text)
"""

from .client import LexiAfrikClient
from .async_client import AsyncLexiAfrikClient
from .models import (
    AccountInfo,
    ApiKey,
    FolderItem,
    Language,
    NewApiKey,
    SegmentDetail,
    SegmentPage,
    SegmentResult,
    TranscriptionPage,
    TranscriptionResult,
    TranscriptionSummary,
    URLTranscriptionResult,
    UsageDashboard,
)
from . import formats
from .exceptions import (
    LexiAfrikError,
    AuthenticationError,
    QuotaExceededError,
    RateLimitError,
    NotFoundError,
    AudioTooLargeError,
    UnsupportedFormatError,
    TranscriptionError,
    APIError,
)

__version__ = "2.1.0"
__author__ = "XEL SOFT AI"
__all__ = [
    "LexiAfrikClient",
    "AsyncLexiAfrikClient",
    "formats",
    "ApiKey",
    "NewApiKey",
    "SegmentDetail",
    "SegmentPage",
    "UsageDashboard",
    "FolderItem",
    "TranscriptionResult",
    "URLTranscriptionResult",
    "SegmentResult",
    "AccountInfo",
    "Language",
    "TranscriptionPage",
    "TranscriptionSummary",
    "LexiAfrikError",
    "AuthenticationError",
    "QuotaExceededError",
    "RateLimitError",
    "NotFoundError",
    "AudioTooLargeError",
    "UnsupportedFormatError",
    "TranscriptionError",
    "APIError",
]

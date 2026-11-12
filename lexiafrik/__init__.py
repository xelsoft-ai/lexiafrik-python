"""
LexiAfrik SDK — API de transcription vocale du wolof et des langues africaines

Usage rapide:
    from lexiafrik import LexiAfrikClient

    client = LexiAfrikClient()          # clé : api_key=, LEXIAFRIK_API_KEY ou `lexiafrik login`
    result = client.transcribe("audio.wav", language="wo")
    print(result.text)
"""

from .client import LexiAfrikClient
from .models import (
    AccountInfo,
    Language,
    SegmentResult,
    TranscriptionPage,
    TranscriptionResult,
    TranscriptionSummary,
    URLTranscriptionResult,
)
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

__version__ = "2.0.0"
__author__ = "XEL SOFT AI"
__all__ = [
    "LexiAfrikClient",
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

"""
LexiAfrik SDK — API de transcription vocale Wolof

Usage rapide:
    from lexiafrik import LexiAfrikClient

    client = LexiAfrikClient(api_key="av_votre_clé")
    result = client.transcribe("audio.wav")
    print(result.text)
"""

from .client import LexiAfrikClient
from .models import TranscriptionResult, URLTranscriptionResult, SegmentResult, UsageInfo
from .exceptions import (
    LexiAfrikError,
    AuthenticationError,
    RateLimitError,
    AudioTooLargeError,
    UnsupportedFormatError,
    TranscriptionError,
    APIError,
)

__version__ = "1.0.0"
__author__ = "XEL SOFT AI"
__all__ = [
    "LexiAfrikClient",
    "TranscriptionResult",
    "URLTranscriptionResult",
    "SegmentResult",
    "UsageInfo",
    "LexiAfrikError",
    "AuthenticationError",
    "RateLimitError",
    "AudioTooLargeError",
    "UnsupportedFormatError",
    "TranscriptionError",
    "APIError",
]

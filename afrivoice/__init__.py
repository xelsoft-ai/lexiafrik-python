"""
AfriVoice SDK — API de transcription vocale Wolof

Usage rapide:
    from afrivoice import AfriVoiceClient

    client = AfriVoiceClient(api_key="av_votre_clé")
    result = client.transcribe("audio.wav")
    print(result.text)
"""

from .client import AfriVoiceClient
from .models import TranscriptionResult, URLTranscriptionResult, SegmentResult, UsageInfo
from .exceptions import (
    AfriVoiceError,
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
    "AfriVoiceClient",
    "TranscriptionResult",
    "URLTranscriptionResult",
    "SegmentResult",
    "UsageInfo",
    "AfriVoiceError",
    "AuthenticationError",
    "RateLimitError",
    "AudioTooLargeError",
    "UnsupportedFormatError",
    "TranscriptionError",
    "APIError",
]

"""AfriVoice SDK — Modèles de réponse."""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime


@dataclass
class TranscriptionResult:
    """Résultat d'une transcription audio."""
    text: str
    duration_s: float
    inference_time_s: float
    rtf: float
    n_tokens: int
    request_id: str
    model: str
    timestamp: datetime
    language: str = "wo"

    def __str__(self) -> str:
        return self.text


@dataclass
class SegmentResult:
    """Résultat d'un segment vidéo."""
    index: int
    start_s: float
    end_s: float
    duration_s: float
    text: str
    inference_time_s: float
    rtf: float

    def __str__(self) -> str:
        return f"[{self.start_s:.1f}s → {self.end_s:.1f}s] {self.text}"


@dataclass
class URLTranscriptionResult:
    """Résultat d'une transcription depuis URL vidéo."""
    title: str
    full_text: str
    segments: List[SegmentResult]
    total_duration_s: float
    total_inference_s: float
    mean_rtf: float
    n_segments: int
    request_id: str
    model: str
    timestamp: datetime

    def __str__(self) -> str:
        return self.full_text


@dataclass
class UsageInfo:
    """Informations d'utilisation d'une clé API."""
    api_key_name: str
    tier: str
    today_requests: int
    today_audio_seconds: float
    daily_limit_seconds: int
    remaining_seconds: float
    total_requests: int
    total_audio_seconds: float
    member_since: str

    @property
    def remaining_minutes(self) -> float:
        return round(self.remaining_seconds / 60, 1)

    @property
    def daily_limit_minutes(self) -> float:
        return round(self.daily_limit_seconds / 60, 1)

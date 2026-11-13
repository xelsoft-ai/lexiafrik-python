"""LexiAfrik SDK — Response models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class SegmentResult:
    """A speech segment, with its position in the original audio."""
    index: int
    start_s: float
    end_s: float
    duration_s: float
    text: str
    inference_time_s: float = 0.0
    rtf: float = 0.0
    # Sample rate of this segment's archived audio (None if unknown).
    sample_rate: Optional[int] = None
    # Temporary URL of the segment audio (None when the audio is not kept).
    audio_url: Optional[str] = None

    def __str__(self) -> str:
        return f"[{self.start_s:.1f}s → {self.end_s:.1f}s] {self.text}"


@dataclass
class TranscriptionResult:
    """Result of a transcription (short file, large file or link)."""
    request_id: str
    text: str
    language: Optional[str] = None
    duration_s: float = 0.0
    n_segments: int = 0
    # Filled when include_segments=True (short file), always for asynchronous jobs.
    segments: List[SegmentResult] = field(default_factory=list)
    title: Optional[str] = None
    # Temporary URL of the full audio (asynchronous jobs, when the audio is kept).
    audio_url: Optional[str] = None
    sample_rate: Optional[int] = None
    timestamp: Optional[datetime] = None

    @property
    def full_text(self) -> str:
        return self.text

    def __str__(self) -> str:
        return self.text


# Compatibility with SDK 1.x: a single result type for every mode.
URLTranscriptionResult = TranscriptionResult


@dataclass
class AccountInfo:
    """Plan, monthly quota and credit of the account (shared by all its keys)."""
    plan: str
    plan_name: str
    # None: unlimited quota (custom plan).
    quota_seconds: Optional[float]
    used_seconds: float
    quota_remaining_seconds: Optional[float]
    wallet_usd: float
    wallet_minutes: float
    period_end: Optional[str] = None
    wallet_expires_at: Optional[str] = None
    features: Dict[str, Any] = field(default_factory=dict)

    @property
    def quota_remaining_minutes(self) -> Optional[float]:
        if self.quota_remaining_seconds is None:
            return None
        return round(self.quota_remaining_seconds / 60, 1)

    @property
    def available_minutes(self) -> Optional[float]:
        """Minutes you can transcribe right now: remaining quota + credit (None if unlimited)."""
        if self.quota_remaining_seconds is None:
            return None
        return round(self.quota_remaining_seconds / 60 + self.wallet_minutes, 1)


@dataclass
class Language:
    code: str
    name: str
    aliases: List[str] = field(default_factory=list)


@dataclass
class TranscriptionSummary:
    """One row of the history (list_transcriptions)."""
    request_id: str
    status: str
    text: Optional[str] = None
    title: Optional[str] = None
    language: Optional[str] = None
    duration_s: Optional[float] = None
    timestamp: Optional[str] = None
    error: Optional[str] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class TranscriptionPage:
    items: List[TranscriptionSummary]
    total: int
    page: int
    page_size: int

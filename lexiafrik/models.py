"""LexiAfrik SDK — Modèles de réponse."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class SegmentResult:
    """Un segment de parole, avec sa position dans l'audio d'origine."""
    index: int
    start_s: float
    end_s: float
    duration_s: float
    text: str
    inference_time_s: float = 0.0
    rtf: float = 0.0
    # Fréquence d'échantillonnage de l'audio archivé de ce segment (None si inconnue).
    sample_rate: Optional[int] = None
    # URL temporaire de l'audio du segment (None si l'audio n'est pas conservé).
    audio_url: Optional[str] = None

    def __str__(self) -> str:
        return f"[{self.start_s:.1f}s → {self.end_s:.1f}s] {self.text}"


@dataclass
class TranscriptionResult:
    """Résultat d'une transcription (fichier court, gros fichier ou lien)."""
    request_id: str
    text: str
    language: Optional[str] = None
    duration_s: float = 0.0
    n_segments: int = 0
    # Renseigné si include_segments=True (fichier court), toujours pour les jobs asynchrones.
    segments: List[SegmentResult] = field(default_factory=list)
    title: Optional[str] = None
    # URL temporaire de l'audio complet (jobs asynchrones, quand l'audio est conservé).
    audio_url: Optional[str] = None
    sample_rate: Optional[int] = None
    timestamp: Optional[datetime] = None

    @property
    def full_text(self) -> str:
        return self.text

    def __str__(self) -> str:
        return self.text


# Compatibilité avec le SDK 1.x : un seul type de résultat pour tous les modes.
URLTranscriptionResult = TranscriptionResult


@dataclass
class AccountInfo:
    """Offre, quota mensuel et crédit du compte (partagés par toutes ses clés)."""
    plan: str
    plan_name: str
    # None : quota illimité (offre sur mesure).
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
        """Minutes transcriptibles maintenant : quota restant + crédit (None si illimité)."""
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
    """Une ligne de l'historique (list_transcriptions)."""
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

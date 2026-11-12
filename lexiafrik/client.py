"""
LexiAfrik SDK — Client principal

Usage:
    from lexiafrik import LexiAfrikClient

    client = LexiAfrikClient(api_key="av_votre_clé")

    # Transcrire un fichier
    result = client.transcribe("audio.wav")
    print(result.text)

    # Transcrire depuis YouTube
    result = client.transcribe_url("https://youtube.com/watch?v=...")
    for seg in result.segments:
        print(seg)

    # Consulter l'utilisation
    usage = client.get_usage()
    print(f"Reste: {usage.remaining_minutes} min")
"""

import os
import time
from pathlib import Path
from typing import Union, Optional, BinaryIO
from datetime import datetime

import httpx

from .auth import load_credentials
from .models import (
    TranscriptionResult, URLTranscriptionResult,
    SegmentResult, UsageInfo,
)
from .exceptions import (
    LexiAfrikError, AuthenticationError, RateLimitError,
    AudioTooLargeError, UnsupportedFormatError, TranscriptionError, APIError,
)

DEFAULT_BASE_URL = "https://api.lexiafrik.com"

AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".webm", ".m4a", ".mp4"}


class LexiAfrikClient:
    """
    Client HTTP synchrone pour l'API LexiAfrik.

    Args:
        api_key:  Clé API. Si None : LEXIAFRIK_API_KEY, sinon la clé enregistrée par
                  `lexiafrik login` (~/.lexiafrik/credentials.json).
        base_url: URL de base de l'API. Par défaut : LEXIAFRIK_BASE_URL, sinon celle de
                  la connexion enregistrée, sinon https://api.lexiafrik.com
        timeout:  Timeout en secondes (défaut: 300 pour les longues transcriptions).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 300.0,
    ):
        saved = None
        self.api_key = api_key or os.environ.get("LEXIAFRIK_API_KEY")
        if not self.api_key:
            saved = load_credentials()
            self.api_key = saved["api_key"] if saved else None
        if not self.api_key:
            raise AuthenticationError(
                "Clé API manquante. Passez api_key=, définissez LEXIAFRIK_API_KEY "
                "ou lancez `lexiafrik login`."
            )

        base_url = (base_url or os.environ.get("LEXIAFRIK_BASE_URL")
                    or (saved or {}).get("base_url") or DEFAULT_BASE_URL)
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"X-API-Key": self.api_key},
            timeout=timeout,
        )

    # ================================================================
    # TRANSCRIPTION FICHIER
    # ================================================================

    def transcribe(
        self,
        audio: Union[str, Path, bytes, BinaryIO],
        filename: str = "audio.wav",
    ) -> TranscriptionResult:
        """
        Transcrit un fichier audio en Wolof.

        Args:
            audio:    Chemin vers le fichier (str/Path), bytes bruts, ou file-like object.
            filename: Nom du fichier (utilisé pour l'extension). Ignoré si audio est un chemin.

        Returns:
            TranscriptionResult avec le texte et les métriques.

        Raises:
            AuthenticationError: Clé invalide (401)
            RateLimitError: Limite dépassée (429)
            AudioTooLargeError: Fichier trop volumineux (413)
            UnsupportedFormatError: Format non supporté (415)
            TranscriptionError: Erreur de transcription (422)
            APIError: Autre erreur serveur

        Example:
            result = client.transcribe("discours.wav")
            print(result.text)
            print(f"Durée: {result.duration_s}s, RTF: {result.rtf}")
        """
        if isinstance(audio, (str, Path)):
            path = Path(audio)
            if not path.exists():
                raise LexiAfrikError(f"Fichier introuvable: {audio}")
            filename = path.name
            with open(path, "rb") as f:
                audio_bytes = f.read()
        elif isinstance(audio, bytes):
            audio_bytes = audio
        else:
            audio_bytes = audio.read()

        files = {"file": (filename, audio_bytes, "audio/wav")}
        response = self._client.post("/v1/transcribe", files=files)
        data = self._handle_response(response)

        t = data["transcription"]
        return TranscriptionResult(
            text=t["text"],
            duration_s=t["duration_s"],
            inference_time_s=t["inference_time_s"],
            rtf=t["rtf"],
            n_tokens=t["n_tokens"],
            request_id=data["request_id"],
            model=data["model"],
            timestamp=datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00")),
        )

    # ================================================================
    # TRANSCRIPTION URL
    # ================================================================

    def transcribe_url(
        self,
        url: str,
        min_silence_ms: int = 500,
        silence_thresh_dbfs: int = -35,
        min_segment_s: float = 1.0,
        max_segment_s: float = 30.0,
        poll_interval: float = 3.0,
        job_timeout: float = 1800.0,
    ) -> URLTranscriptionResult:
        """
        Transcrit une vidéo depuis une URL (YouTube, etc.).

        Soumet un job asynchrone (HTTP 202) puis poll automatiquement
        GET /v1/tasks/{task_id} jusqu'à obtenir le résultat final.

        Args:
            url:                 URL de la vidéo.
            min_silence_ms:      Silence min pour couper (ms, défaut: 500).
            silence_thresh_dbfs: Seuil de silence en dBFS (défaut: -35).
            min_segment_s:       Durée min d'un segment en secondes (défaut: 1.0).
            max_segment_s:       Durée max d'un segment en secondes (défaut: 30.0).
            poll_interval:       Secondes entre chaque poll (défaut: 3).
            job_timeout:         Timeout total en secondes (défaut: 1800).

        Returns:
            URLTranscriptionResult avec les segments et le texte complet.

        Raises:
            TranscriptionError: Erreur de transcription ou timeout dépassé.

        Example:
            result = client.transcribe_url("https://youtube.com/watch?v=abc123")
            print(result.full_text)
            for seg in result.segments:
                print(f"[{seg.start_s:.1f}s] {seg.text}")
        """
        payload = {
            "url": url,
            "min_silence_ms": min_silence_ms,
            "silence_thresh_dbfs": silence_thresh_dbfs,
            "min_segment_s": min_segment_s,
            "max_segment_s": max_segment_s,
        }

        # Soumettre le job — l'API répond 202 immédiatement
        response = self._client.post("/v1/transcribe-url", json=payload)
        if response.status_code != 202:
            self._handle_response(response)  # lève l'exception appropriée

        task_id = response.json()["task_id"]

        # Poller GET /v1/tasks/{task_id} jusqu'au résultat
        deadline = time.monotonic() + job_timeout
        while time.monotonic() < deadline:
            resp = self._client.get(f"/v1/tasks/{task_id}")
            data = self._handle_response(resp)

            status = data["status"]

            if status == "processing":
                time.sleep(poll_interval)
                continue

            if status == "error":
                raise TranscriptionError(data.get("error") or "Erreur de transcription.")

            # status == "success"
            segments = [
                SegmentResult(
                    index=s["index"],
                    start_s=s["start_s"],
                    end_s=s["end_s"],
                    duration_s=s["duration_s"],
                    text=s["text"],
                    inference_time_s=s["inference_time_s"],
                    rtf=s["rtf"],
                    sample_rate=s.get("sample_rate"),
                )
                for s in (data.get("segments") or [])
            ]

            ts = str(data.get("timestamp") or "")
            return URLTranscriptionResult(
                title=data.get("title") or "",
                full_text=data.get("full_text") or "",
                segments=segments,
                total_duration_s=data.get("total_duration_s") or 0.0,
                total_inference_s=data.get("total_inference_s") or 0.0,
                mean_rtf=data.get("mean_rtf") or 0.0,
                n_segments=data.get("n_segments") or len(segments),
                request_id=task_id,
                model=data.get("model") or "",
                timestamp=datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else datetime.now(),
                sample_rate=data.get("sample_rate"),
            )

        raise TranscriptionError(f"Timeout ({job_timeout}s) atteint pour le job '{task_id}'.")

    # ================================================================
    # USAGE
    # ================================================================

    def get_usage(self) -> UsageInfo:
        """
        Consulte la consommation de votre clé API.

        Returns:
            UsageInfo avec les compteurs du jour et les totaux.

        Example:
            usage = client.get_usage()
            print(f"Tier: {usage.tier}")
            print(f"Aujourd'hui: {usage.today_requests} requêtes")
            print(f"Audio restant: {usage.remaining_minutes} min")
        """
        response = self._client.get("/v1/usage")
        data = self._handle_response(response)

        return UsageInfo(
            api_key_name=data["api_key_name"],
            tier=data["tier"],
            today_requests=data["today_requests"],
            today_audio_seconds=data["today_audio_seconds"],
            daily_limit_seconds=data["daily_limit_seconds"],
            remaining_seconds=data["remaining_seconds"],
            total_requests=data["total_requests"],
            total_audio_seconds=data["total_audio_seconds"],
            member_since=data["member_since"],
        )

    # ================================================================
    # HEALTH
    # ================================================================

    def health(self) -> dict:
        """Vérifie que l'API est opérationnelle."""
        response = self._client.get("/health")
        return self._handle_response(response)

    # ================================================================
    # INTERNAL
    # ================================================================

    def _handle_response(self, response: httpx.Response) -> dict:
        """Convertit la réponse HTTP en dict ou lève une exception appropriée."""
        if response.status_code == 200:
            return response.json()

        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text

        if response.status_code == 401:
            raise AuthenticationError(detail)
        elif response.status_code == 403:
            raise AuthenticationError(f"Accès refusé: {detail}")
        elif response.status_code == 413:
            raise AudioTooLargeError(detail)
        elif response.status_code == 415:
            raise UnsupportedFormatError(detail)
        elif response.status_code == 422:
            raise TranscriptionError(detail)
        elif response.status_code == 429:
            raise RateLimitError(detail)
        else:
            raise APIError(detail, status_code=response.status_code)

    def close(self):
        """Ferme le client HTTP."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

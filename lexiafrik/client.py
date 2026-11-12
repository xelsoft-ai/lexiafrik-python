"""
LexiAfrik SDK — Client principal

    from lexiafrik import LexiAfrikClient

    client = LexiAfrikClient()                  # clé : api_key=, LEXIAFRIK_API_KEY ou `lexiafrik login`

    result = client.transcribe("discours.wav", language="wo")       # fichier court (≤ 50 Mo)
    print(result.text)

    result = client.transcribe_large("conference.mp4")              # gros fichier ou vidéo
    for seg in result.segments:
        print(seg)

    print(client.get_account().available_minutes, "min disponibles")
"""

import mimetypes
import os
import time
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Callable, Iterator, List, Optional, Union

import httpx

from .auth import DEFAULT_BASE_URL, load_credentials
from .exceptions import (
    APIError, AudioTooLargeError, AuthenticationError, LexiAfrikError, NotFoundError,
    QuotaExceededError, RateLimitError, TranscriptionError, UnsupportedFormatError,
)
from .models import (
    AccountInfo, Language, SegmentResult, TranscriptionPage, TranscriptionResult,
    TranscriptionSummary,
)

_CHUNK = 1024 * 1024


def _parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _segments(raw) -> List[SegmentResult]:
    return [
        SegmentResult(
            index=s["index"], start_s=s["start_s"], end_s=s["end_s"], duration_s=s["duration_s"],
            text=s.get("text") or "", inference_time_s=s.get("inference_time_s") or 0.0,
            rtf=s.get("rtf") or 0.0, sample_rate=s.get("sample_rate"), audio_url=s.get("audio_url"),
        )
        for s in (raw or [])
    ]


def _result(data: dict, request_id: str) -> TranscriptionResult:
    segs = _segments(data.get("segments"))
    return TranscriptionResult(
        request_id=request_id,
        text=data.get("full_text") or "",
        language=data.get("language"),
        duration_s=data.get("total_duration_s") or 0.0,
        n_segments=data.get("n_segments") or len(segs),
        segments=segs,
        title=data.get("title"),
        audio_url=data.get("audio_url"),
        sample_rate=data.get("sample_rate"),
        timestamp=_parse_dt(data.get("timestamp")),
    )


def _file_chunks(path: Path) -> Iterator[bytes]:
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_CHUNK)
            if not chunk:
                return
            yield chunk


class LexiAfrikClient:
    """
    Client HTTP synchrone pour l'API LexiAfrik.

    Args:
        api_key:  Clé API. Si None : LEXIAFRIK_API_KEY, sinon la clé enregistrée par
                  `lexiafrik login` (~/.lexiafrik/credentials.json).
        base_url: URL de base de l'API. Par défaut : LEXIAFRIK_BASE_URL, sinon celle de
                  la connexion enregistrée, sinon https://api.lexiafrik.com
        timeout:  Délai par requête, en secondes (défaut : 300).
        transport: Transport httpx personnalisé (tests).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 300.0,
        transport: Optional[httpx.BaseTransport] = None,
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
            base_url=self.base_url, headers={"X-API-Key": self.api_key},
            timeout=timeout, transport=transport,
        )
        # Envoi des fichiers vers le stockage : sans la clé API (URL signée).
        self._storage = httpx.Client(timeout=timeout, transport=transport)

    # ================================================================
    # FICHIER COURT (réponse immédiate)
    # ================================================================

    def transcribe(
        self,
        audio: Union[str, Path, bytes, BinaryIO],
        filename: str = "audio.wav",
        language: Optional[str] = None,
        include_segments: bool = False,
        keep_audio: bool = True,
    ) -> TranscriptionResult:
        """
        Transcrit un fichier audio (50 Mo maximum) et renvoie le résultat directement.
        Pour un fichier plus gros ou une vidéo, utilisez transcribe_large().

        Args:
            audio:            Chemin (str/Path), octets bruts ou fichier ouvert en binaire.
            filename:         Nom du fichier (son extension compte). Ignoré pour un chemin.
            language:         Langue de l'audio : `wo`, `wo-SN`, `ha`, `fr`… (voir list_languages()).
                              Défaut côté API : wolof.
            include_segments: Renvoie aussi les segments horodatés.
            keep_audio:       False : seul le texte est conservé, pas l'audio.

        Raises:
            AuthenticationError, QuotaExceededError (402), AudioTooLargeError (413),
            UnsupportedFormatError (415), TranscriptionError (422), APIError.

        Example:
            result = client.transcribe("discours.wav", language="wo", include_segments=True)
            print(result.text)
        """
        if isinstance(audio, (str, Path)):
            path = Path(audio)
            if not path.is_file():
                raise LexiAfrikError(f"Fichier introuvable: {audio}")
            filename = path.name
            content = path.read_bytes()
        elif isinstance(audio, bytes):
            content = audio
        else:
            content = audio.read()

        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        form = {"include_segments": str(include_segments).lower(), "keep_audio": str(keep_audio).lower()}
        if language:
            form["language"] = language
        data = self._handle_response(self._client.post(
            "/v1/transcribe", files={"file": (filename, content, ctype)}, data=form))
        return _result(data, data.get("request_id", ""))

    # ================================================================
    # GROS FICHIERS, VIDÉOS, LIENS (job asynchrone)
    # ================================================================

    def upload(self, file: Union[str, Path], content_type: Optional[str] = None) -> str:
        """
        Envoie un fichier audio ou vidéo directement vers le stockage (il ne transite pas par l'API)
        et renvoie son `upload_key`, à passer à transcribe_url(upload_key=...).
        """
        path = Path(file)
        if not path.is_file():
            raise LexiAfrikError(f"Fichier introuvable: {file}")
        ctype = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        size = path.stat().st_size

        slot = self._handle_response(self._client.post(
            "/v1/uploads", json={"filename": path.name, "content_type": ctype}))
        max_mb = slot.get("max_size_mb")
        if max_mb and size > max_mb * 1024 * 1024:
            raise AudioTooLargeError(
                f"Fichier de {size / 1024 / 1024:.0f} Mo : votre offre accepte {max_mb} Mo au maximum.")

        headers = {**(slot.get("headers") or {}), "Content-Length": str(size)}
        resp = self._storage.request(slot.get("method", "PUT"), slot["upload_url"],
                                     headers=headers, content=_file_chunks(path))
        if resp.status_code >= 300:
            raise APIError(f"Échec de l'envoi du fichier (HTTP {resp.status_code}).", status_code=resp.status_code)
        return slot["upload_key"]

    def start_transcription(
        self,
        url: Optional[str] = None,
        *,
        upload_key: Optional[str] = None,
        language: Optional[str] = None,
        title: Optional[str] = None,
        keep_audio: bool = True,
        webhook_url: Optional[str] = None,
    ) -> str:
        """Lance un job asynchrone (lien direct `url` ou `upload_key`) et renvoie son `task_id`."""
        if bool(url) == bool(upload_key):
            raise LexiAfrikError("Fournissez soit url=, soit upload_key=.")
        payload = {"keep_audio": keep_audio, "include_segments": True}
        for k, v in (("url", url), ("upload_key", upload_key), ("language", language),
                     ("title", title), ("webhook_url", webhook_url)):
            if v:
                payload[k] = v
        return self._handle_response(self._client.post("/v1/transcribe-url", json=payload))["task_id"]

    def get_task(self, task_id: str) -> dict:
        """État brut d'un job : `status` vaut processing, success ou error."""
        return self._handle_response(self._client.get(f"/v1/tasks/{task_id}"))

    def wait_for_task(
        self,
        task_id: str,
        poll_interval: float = 3.0,
        job_timeout: float = 3600.0,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> TranscriptionResult:
        """
        Attend la fin d'un job. `on_progress(n)` est appelé avec le nombre de segments déjà
        transcrits à chaque interrogation.

        Raises:
            TranscriptionError: job en échec, ou délai dépassé.
        """
        deadline = time.monotonic() + job_timeout
        while time.monotonic() < deadline:
            resp = self._client.get(f"/v1/tasks/{task_id}")
            data = self._handle_response(resp)
            status = data.get("status")
            if status == "success":
                return _result(data, task_id)
            if status == "error":
                raise TranscriptionError(data.get("error") or "Erreur de transcription.")
            if on_progress:
                on_progress(len(data.get("segments") or []))
            try:
                wait = float(resp.headers.get("Retry-After") or poll_interval)
            except ValueError:
                wait = poll_interval
            time.sleep(max(wait, 0.0))
        raise TranscriptionError(f"Délai de {job_timeout:.0f}s dépassé pour la tâche '{task_id}'.")

    def transcribe_url(
        self,
        url: Optional[str] = None,
        *,
        upload_key: Optional[str] = None,
        language: Optional[str] = None,
        title: Optional[str] = None,
        keep_audio: bool = True,
        poll_interval: float = 3.0,
        job_timeout: float = 3600.0,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> TranscriptionResult:
        """
        Transcrit un fichier audio/vidéo accessible par un lien direct (`url`, http ou https)
        ou déjà envoyé (`upload_key`), et attend le résultat. Les liens de plateformes de
        streaming (YouTube, TikTok…) ne sont pas acceptés.
        """
        task_id = self.start_transcription(url, upload_key=upload_key, language=language,
                                           title=title, keep_audio=keep_audio)
        return self.wait_for_task(task_id, poll_interval, job_timeout, on_progress)

    def transcribe_large(
        self,
        file: Union[str, Path],
        language: Optional[str] = None,
        title: Optional[str] = None,
        keep_audio: bool = True,
        poll_interval: float = 3.0,
        job_timeout: float = 3600.0,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> TranscriptionResult:
        """
        Transcrit un gros fichier ou une vidéo : envoi direct, job asynchrone, attente du résultat.

        Example:
            result = client.transcribe_large("conference.mp4", language="wo",
                                             on_progress=lambda n: print(n, "segments"))
            print(result.text)
        """
        path = Path(file)
        key = self.upload(path)
        return self.transcribe_url(upload_key=key, language=language, title=title or path.name,
                                   keep_audio=keep_audio, poll_interval=poll_interval,
                                   job_timeout=job_timeout, on_progress=on_progress)

    # ================================================================
    # LANGUES, COMPTE, HISTORIQUE
    # ================================================================

    def list_languages(self) -> List[Language]:
        """Langues disponibles (route publique)."""
        data = self._handle_response(self._client.get("/v1/languages"))
        return [Language(code=l["code"], name=l["name"], aliases=l.get("aliases") or [])
                for l in data.get("languages", [])]

    def get_account(self) -> AccountInfo:
        """Offre, quota mensuel restant et crédit du compte."""
        d = self._handle_response(self._client.get("/v1/billing/account"))
        return AccountInfo(
            plan=d["plan"], plan_name=d.get("plan_name") or d["plan"],
            quota_seconds=d.get("quota_seconds"), used_seconds=d.get("used_seconds") or 0.0,
            quota_remaining_seconds=d.get("quota_remaining_seconds"),
            wallet_usd=d.get("wallet_usd") or 0.0, wallet_minutes=d.get("wallet_minutes") or 0.0,
            period_end=str(d["period_end"]) if d.get("period_end") else None,
            wallet_expires_at=str(d["wallet_expires_at"]) if d.get("wallet_expires_at") else None,
            features=d.get("features") or {},
        )

    # Nom du SDK 1.x : les limites journalières n'existent plus, l'offre et le quota mensuel les remplacent.
    get_usage = get_account

    def list_transcriptions(self, page: int = 1, page_size: int = 20,
                            status: Optional[str] = None) -> TranscriptionPage:
        """Historique de vos transcriptions, de la plus récente à la plus ancienne."""
        params = {"page": page, "page_size": page_size}
        if status:
            params["status"] = status
        d = self._handle_response(self._client.get("/v1/transcriptions", params=params))
        items = [
            TranscriptionSummary(
                request_id=r["request_id"], status=r.get("status") or "", text=r.get("text"),
                title=r.get("source_title"), language=r.get("language"), duration_s=r.get("duration_s"),
                timestamp=str(r["timestamp"]) if r.get("timestamp") else None,
                error=r.get("error_message"), tags=r.get("tags") or [],
            )
            for r in d.get("items", [])
        ]
        return TranscriptionPage(items=items, total=d.get("total", len(items)), page=page, page_size=page_size)

    def get_transcription(self, request_id: str) -> dict:
        """Détail d'une transcription (texte, segments, corrections) tel que renvoyé par l'API."""
        return self._handle_response(self._client.get(f"/v1/transcriptions/{request_id}"))

    def delete_transcription(self, request_id: str) -> None:
        """Supprime une transcription et ses fichiers (irréversible)."""
        self._handle_response(self._client.delete(f"/v1/transcriptions/{request_id}"))

    def health(self) -> dict:
        """Vérifie que l'API est opérationnelle."""
        return self._handle_response(self._client.get("/health"))

    # ================================================================
    # INTERNE
    # ================================================================

    def _handle_response(self, response: httpx.Response) -> dict:
        """Convertit la réponse HTTP en dict ou lève l'exception appropriée."""
        if response.status_code < 300:
            return response.json() if response.content else {}

        try:
            body = response.json()
            detail = body.get("detail") or body.get("error") or response.text
        except Exception:
            detail = response.text
        if isinstance(detail, list):  # erreur de validation (422)
            detail = "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)

        code = response.status_code
        if code in (401, 403):
            raise AuthenticationError(detail if code == 401 else f"Accès refusé: {detail}")
        if code == 402:
            raise QuotaExceededError(detail)
        if code == 404:
            raise NotFoundError(detail)
        if code == 413:
            raise AudioTooLargeError(detail)
        if code == 415:
            raise UnsupportedFormatError(detail)
        if code == 422:
            raise TranscriptionError(detail)
        if code == 429:
            raise RateLimitError(detail)
        raise APIError(detail, status_code=code)

    def close(self):
        """Ferme les connexions HTTP."""
        self._client.close()
        self._storage.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

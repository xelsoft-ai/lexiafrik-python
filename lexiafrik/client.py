"""
LexiAfrik SDK — Main client

    from lexiafrik import LexiAfrikClient

    client = LexiAfrikClient()                  # key: api_key=, LEXIAFRIK_API_KEY or `lexiafrik login`

    result = client.transcribe("speech.wav", language="wo")         # short file (≤ 50 MB)
    print(result.text)

    result = client.transcribe_large("conference.mp4")              # large file or video
    for seg in result.segments:
        print(seg)

    print(client.get_account().available_minutes, "minutes available")
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
    Synchronous HTTP client for the LexiAfrik API.

    Args:
        api_key:  API key. If None: LEXIAFRIK_API_KEY, otherwise the key saved by
                  `lexiafrik login` (~/.lexiafrik/credentials.json).
        base_url: API base URL. Default: LEXIAFRIK_BASE_URL, otherwise the one of the saved
                  sign-in, otherwise https://api.lexiafrik.com
        timeout:  Timeout per request, in seconds (default: 300).
        transport: Custom httpx transport (tests).
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
                "Missing API key. Pass api_key=, set LEXIAFRIK_API_KEY "
                "or run `lexiafrik login`."
            )

        base_url = (base_url or os.environ.get("LEXIAFRIK_BASE_URL")
                    or (saved or {}).get("base_url") or DEFAULT_BASE_URL)
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"X-API-Key": self.api_key, "Accept-Language": os.environ.get("LEXIAFRIK_LANG", "en")},
            timeout=timeout, transport=transport,
        )
        # File uploads go to storage without the API key (signed URL).
        self._storage = httpx.Client(timeout=timeout, transport=transport)

    # ================================================================
    # SHORT FILE (immediate response)
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
        Transcribe an audio file (50 MB maximum) and return the result directly.
        For a larger file or a video, use transcribe_large().

        Args:
            audio:            Path (str/Path), raw bytes or a file opened in binary mode.
            filename:         File name (its extension matters). Ignored for a path.
            language:         Language of the audio: `wo`, `wo-SN`, `ha`, `fr`… (see list_languages()).
                              API default: Wolof.
            include_segments: Also return the timestamped segments.
            keep_audio:       False: only the text is kept, not the audio.

        Raises:
            AuthenticationError, QuotaExceededError (402), AudioTooLargeError (413),
            UnsupportedFormatError (415), TranscriptionError (422), APIError.

        Example:
            result = client.transcribe("speech.wav", language="wo", include_segments=True)
            print(result.text)
        """
        if isinstance(audio, (str, Path)):
            path = Path(audio)
            if not path.is_file():
                raise LexiAfrikError(f"File not found: {audio}")
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
    # LARGE FILES, VIDEOS, LINKS (asynchronous job)
    # ================================================================

    def upload(self, file: Union[str, Path], content_type: Optional[str] = None) -> str:
        """
        Upload an audio or video file straight to storage (it does not go through the API)
        and return its `upload_key`, to pass to transcribe_url(upload_key=...).
        """
        path = Path(file)
        if not path.is_file():
            raise LexiAfrikError(f"File not found: {file}")
        ctype = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        size = path.stat().st_size

        slot = self._handle_response(self._client.post(
            "/v1/uploads", json={"filename": path.name, "content_type": ctype}))
        max_mb = slot.get("max_size_mb")
        if max_mb and size > max_mb * 1024 * 1024:
            raise AudioTooLargeError(
                f"File of {size / 1024 / 1024:.0f} MB: your plan accepts {max_mb} MB at most.")

        headers = {**(slot.get("headers") or {}), "Content-Length": str(size)}
        resp = self._storage.request(slot.get("method", "PUT"), slot["upload_url"],
                                     headers=headers, content=_file_chunks(path))
        if resp.status_code >= 300:
            raise APIError(f"File upload failed (HTTP {resp.status_code}).", status_code=resp.status_code)
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
        """Start an asynchronous job (direct link `url` or `upload_key`) and return its `task_id`."""
        if bool(url) == bool(upload_key):
            raise LexiAfrikError("Provide either url= or upload_key=.")
        payload = {"keep_audio": keep_audio, "include_segments": True}
        for k, v in (("url", url), ("upload_key", upload_key), ("language", language),
                     ("title", title), ("webhook_url", webhook_url)):
            if v:
                payload[k] = v
        return self._handle_response(self._client.post("/v1/transcribe-url", json=payload))["task_id"]

    def get_task(self, task_id: str) -> dict:
        """Raw state of a job: `status` is processing, success or error."""
        return self._handle_response(self._client.get(f"/v1/tasks/{task_id}"))

    def wait_for_task(
        self,
        task_id: str,
        poll_interval: float = 3.0,
        job_timeout: float = 3600.0,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> TranscriptionResult:
        """
        Wait for a job to finish. `on_progress(n)` is called with the number of segments already
        transcribed at each poll.

        Raises:
            TranscriptionError: failed job, or timeout.
        """
        deadline = time.monotonic() + job_timeout
        while time.monotonic() < deadline:
            resp = self._client.get(f"/v1/tasks/{task_id}")
            data = self._handle_response(resp)
            status = data.get("status")
            if status == "success":
                return _result(data, task_id)
            if status == "error":
                raise TranscriptionError("Transcription failed.", detail=data.get("error"))
            if on_progress:
                on_progress(len(data.get("segments") or []))
            try:
                wait = float(resp.headers.get("Retry-After") or poll_interval)
            except ValueError:
                wait = poll_interval
            time.sleep(max(wait, 0.0))
        raise TranscriptionError(f"Timed out after {job_timeout:.0f}s waiting for task '{task_id}'.")

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
        Transcribe an audio/video file reachable through a direct link (`url`, http or https)
        or already uploaded (`upload_key`), and wait for the result. Links to streaming
        platforms (YouTube, TikTok…) are not accepted.
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
        Transcribe a large file or a video: direct upload, asynchronous job, wait for the result.

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
    # LANGUAGES, ACCOUNT, HISTORY
    # ================================================================

    def list_languages(self) -> List[Language]:
        """Available languages (public route)."""
        data = self._handle_response(self._client.get("/v1/languages"))
        return [Language(code=l["code"], name=l["name"], aliases=l.get("aliases") or [])
                for l in data.get("languages", [])]

    def get_account(self) -> AccountInfo:
        """Plan, remaining monthly quota and credit of the account."""
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

    # SDK 1.x name: daily limits no longer exist, the plan and the monthly quota replace them.
    get_usage = get_account

    def list_transcriptions(self, page: int = 1, page_size: int = 20,
                            status: Optional[str] = None) -> TranscriptionPage:
        """History of your transcriptions, newest first."""
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
        """Details of a transcription (text, segments, corrections) as returned by the API."""
        return self._handle_response(self._client.get(f"/v1/transcriptions/{request_id}"))

    def delete_transcription(self, request_id: str) -> None:
        """Delete a transcription and its files (irreversible)."""
        self._handle_response(self._client.delete(f"/v1/transcriptions/{request_id}"))

    def health(self) -> dict:
        """Check that the API is up."""
        return self._handle_response(self._client.get("/health"))

    # ================================================================
    # INTERNAL
    # ================================================================

    def _handle_response(self, response: httpx.Response) -> dict:
        """Turn the HTTP response into a dict, or raise the matching exception.

        The message is always English; the server's own text (its language is the server's)
        is kept in the exception's ``detail`` attribute and shown after the message."""
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

    def close(self):
        """Close the HTTP connections."""
        self._client.close()
        self._storage.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

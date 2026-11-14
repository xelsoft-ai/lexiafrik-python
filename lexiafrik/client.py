"""
LexiAfrik SDK — Main client

    from lexiafrik import LexiAfrikClient

    client = LexiAfrikClient()                  # key: api_key=, LEXIAFRIK_API_KEY or `lexiafrik login`

    result = client.transcribe("speech.wav", language="wo")         # short file (≤ 50 MB)
    print(result.text)

    result = client.transcribe_large("conference.mp4")              # large file or video
    open("conference.srt", "w", encoding="utf-8").write(result.to_srt())

    print(client.get_account().available_minutes, "minutes available")

An asynchronous twin lives in ``lexiafrik.AsyncLexiAfrikClient``.
"""

import mimetypes
import os
import time
from pathlib import Path
from typing import Any, BinaryIO, Callable, Dict, Iterator, List, Optional, Union

import httpx

from ._http import RetryPolicy, raise_for_response
from ._parse import (
    normalize_tags, parse_account, parse_dashboard, parse_history, parse_key, parse_languages, parse_new_key,
    parse_result, parse_segment_page,
)
from .auth import DEFAULT_BASE_URL, load_credentials
from .exceptions import APIError, AudioTooLargeError, AuthenticationError, LexiAfrikError, TranscriptionError
from .models import (
    AccountInfo, ApiKey, FolderItem, Language, NewApiKey, SegmentPage, TranscriptionPage, TranscriptionResult,
    UsageDashboard,
)

_CHUNK = 1024 * 1024
_UNSET: Any = object()  # "argument not given" (None has a meaning: clear the correction)


def _file_chunks(path: Path) -> Iterator[bytes]:
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_CHUNK)
            if not chunk:
                return
            yield chunk


def _meta_body(edited_text: Any, tags: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    if edited_text is not _UNSET:
        body["edited_text"] = edited_text
    if tags is not _UNSET:
        body["tags"] = normalize_tags(tags or [])
    if not body:
        raise LexiAfrikError("Nothing to update: pass edited_text= and/or tags=.")
    return body


class LexiAfrikClient:
    """
    Synchronous HTTP client for the LexiAfrik API.

    Args:
        api_key:  API key. If None: LEXIAFRIK_API_KEY, otherwise the key saved by
                  `lexiafrik login` (~/.lexiafrik/credentials.json).
        base_url: API base URL. Default: LEXIAFRIK_BASE_URL, otherwise the one of the saved
                  sign-in, otherwise https://api.lexiafrik.com
        timeout:  Timeout per request, in seconds (default: 300).
        max_retries: Automatic retries after a network error, HTTP 429 or 503 (default: 3; 0 disables).
                  Requests that create something are never repeated after a timeout (see ``RetryPolicy``).
        transport: Custom httpx transport (tests).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 300.0,
        transport: Optional[httpx.BaseTransport] = None,
        max_retries: int = 3,
        retry_backoff: float = 0.5,
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
        # File uploads go to storage without the API key (signed URL): that client is created on first use.
        self._storage_client: Optional[httpx.Client] = None
        self._timeout = timeout
        self._transport = transport
        self._retry = RetryPolicy(max_retries=max_retries, backoff=retry_backoff)
        self._sleep = time.sleep  # replaced in tests

    @property
    def _storage(self) -> httpx.Client:
        if self._storage_client is None:
            self._storage_client = httpx.Client(timeout=self._timeout, transport=self._transport)
        return self._storage_client

    # ================================================================
    # TRANSPORT (retries, error mapping)
    # ================================================================

    def _send(self, method: str, url: str, **kwargs) -> httpx.Response:
        """One HTTP call with automatic retries (network errors, 429, 503 — and 500/502/504 for safe methods)."""
        attempt = 0
        while True:
            try:
                resp = self._client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                if attempt < self._retry.max_retries and self._retry.retry_exception(method, exc):
                    attempt += 1
                    self._sleep(self._retry.delay(attempt))
                    continue
                raise APIError(f"Could not reach the LexiAfrik API ({type(exc).__name__}: {exc}).") from exc
            if attempt < self._retry.max_retries and self._retry.retry_status(method, resp.status_code):
                attempt += 1
                self._sleep(self._retry.delay(attempt, resp))
                continue
            return resp

    def _call(self, method: str, url: str, **kwargs) -> dict:
        return raise_for_response(self._send(method, url, **kwargs))

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
            include_segments: Also return the timestamped segments (needed for SRT / WebVTT output).
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
        data = self._call("POST", "/v1/transcribe", files={"file": (filename, content, ctype)}, data=form)
        return parse_result(data, data.get("request_id", ""))

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

        slot = self._call("POST", "/v1/uploads", json={"filename": path.name, "content_type": ctype})
        max_mb = slot.get("max_size_mb")
        if max_mb and size > max_mb * 1024 * 1024:
            raise AudioTooLargeError(
                f"File of {size / 1024 / 1024:.0f} MB: your plan accepts {max_mb} MB at most.")

        headers = {**(slot.get("headers") or {}), "Content-Length": str(size)}
        try:
            resp = self._storage.request(slot.get("method", "PUT"), slot["upload_url"],
                                         headers=headers, content=_file_chunks(path))
        except httpx.HTTPError as exc:
            raise APIError(f"File upload failed ({type(exc).__name__}: {exc}).") from exc
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
        return self._call("POST", "/v1/transcribe-url", json=payload)["task_id"]

    def get_task(self, task_id: str) -> dict:
        """Raw state of a job: `status` is processing, success or error."""
        return self._call("GET", f"/v1/tasks/{task_id}")

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
            resp = self._send("GET", f"/v1/tasks/{task_id}")
            data = raise_for_response(resp)
            status = data.get("status")
            if status == "success":
                return parse_result(data, task_id)
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
    # SEVERAL FILES, WHOLE FOLDERS
    # ================================================================

    def transcribe_folder(
        self,
        folder: Union[str, Path],
        *,
        language: Optional[str] = None,
        output_format: Optional[str] = None,
        out_dir: Optional[Union[str, Path]] = None,
        recursive: bool = False,
        skip_existing: bool = True,
        jobs: int = 2,
        keep_audio: bool = True,
        on_item: Optional[Callable[[FolderItem], None]] = None,
    ) -> List[FolderItem]:
        """
        Transcribe every audio and video file of a folder (or a single file), ``jobs`` at a time.

        Args:
            output_format: ``"txt"``, ``"srt"``, ``"vtt"`` or ``"json"``: write each transcription to disk
                           (next to the source file, or under ``out_dir``). None: only return the results.
            skip_existing: do not send again a file whose output already exists (resume an interrupted run).
            on_item:       called as each file finishes (progress display).

        Returns:
            One ``FolderItem`` per file (status ``success``, ``error`` or ``skipped``). One failing file never
            stops the others.
        """
        from . import batch
        root = Path(folder)
        files = batch.find_media(root, recursive)
        return batch.transcribe_files(self, files, language=language, output_format=output_format,
                                      out_dir=out_dir, root=root, skip_existing=skip_existing, jobs=jobs,
                                      keep_audio=keep_audio, on_item=on_item)

    # ================================================================
    # LANGUAGES, ACCOUNT, HISTORY
    # ================================================================

    def list_languages(self) -> List[Language]:
        """Available languages (public route)."""
        return parse_languages(self._call("GET", "/v1/languages"))

    def get_account(self) -> AccountInfo:
        """Plan, remaining monthly quota and credit of the account."""
        return parse_account(self._call("GET", "/v1/billing/account"))

    # SDK 1.x name: daily limits no longer exist, the plan and the monthly quota replace them.
    get_usage = get_account

    def get_usage_dashboard(self, period: str = "7d") -> UsageDashboard:
        """Usage of the account: today, this month, history, languages, per-key breakdown.
        ``period`` is ``"7d"``, ``"30d"`` or ``"month"``."""
        return parse_dashboard(self._call("GET", "/v1/usage/dashboard", params={"period": period}))

    def list_transcriptions(self, page: int = 1, page_size: int = 20,
                            status: Optional[str] = None) -> TranscriptionPage:
        """History of your transcriptions, newest first."""
        params: Dict[str, Any] = {"page": page, "page_size": page_size}
        if status:
            params["status"] = status
        return parse_history(self._call("GET", "/v1/transcriptions", params=params), page, page_size)

    def get_transcription(self, request_id: str) -> dict:
        """Details of a transcription (text, corrections, tags, original file) as returned by the API."""
        return self._call("GET", f"/v1/transcriptions/{request_id}")

    def delete_transcription(self, request_id: str) -> None:
        """Delete a transcription and its files (irreversible)."""
        self._call("DELETE", f"/v1/transcriptions/{request_id}")

    # ================================================================
    # SEGMENTS, CORRECTIONS, TAGS
    # ================================================================

    def get_segments(self, request_id: str, *, q: Optional[str] = None, offset: int = 0,
                     limit: Optional[int] = None) -> SegmentPage:
        """Segments of a stored transcription, with corrections and tags.

        Args:
            q:      search in the text, the corrections, the tags or the language (``"wolof"``, ``"fr"``…).
            limit:  page size; None returns every segment (export).
        """
        params: Dict[str, Any] = {"offset": offset}
        if limit is not None:
            params["limit"] = limit
        if q:
            params["q"] = q
        return parse_segment_page(self._call("GET", f"/v1/transcriptions/{request_id}/segments", params=params),
                                  offset, limit)

    def update_transcription(self, request_id: str, *, edited_text: Any = _UNSET, tags: Any = _UNSET) -> dict:
        """Correct the text of a whole transcription and/or replace its tags.

        ``edited_text=None`` (or an empty string) removes the correction. ``tags`` is a dict
        (``{"topic": "interview"}``) or a list of ``{"key", "value"}``; ``tags={}`` removes them all.
        Arguments you do not pass are left unchanged.
        """
        return self._call("PATCH", f"/v1/transcriptions/{request_id}", json=_meta_body(edited_text, tags))

    def update_segment(self, request_id: str, segment_id: int, *, edited_text: Any = _UNSET,
                       tags: Any = _UNSET) -> dict:
        """Correct one segment and/or replace its tags (same rules as ``update_transcription``).
        When the text changes, the corrected text of the whole transcription is recomputed and returned."""
        return self._call("PATCH", f"/v1/transcriptions/{request_id}/segments/{segment_id}",
                          json=_meta_body(edited_text, tags))

    def delete_segment(self, request_id: str, segment_id: int) -> dict:
        """Delete one segment and its audio (irreversible)."""
        return self._call("DELETE", f"/v1/transcriptions/{request_id}/segments/{segment_id}")

    def get_audio_url(self, request_id: str, segment_id: Optional[int] = None) -> str:
        """Temporary URL (about one hour) of the full audio, or of one segment's audio."""
        path = f"/v1/transcriptions/{request_id}" + (f"/segments/{segment_id}" if segment_id is not None else "")
        return self._call("GET", path + "/audio")["url"]

    # ================================================================
    # API KEYS
    # ================================================================

    def list_keys(self) -> List[ApiKey]:
        """The API keys of your account (the main key first). Secrets are never returned."""
        return [parse_key(k) for k in self._call("GET", "/v1/keys").get("keys", [])]

    def create_key(self, name: str, description: Optional[str] = None, notify: bool = True) -> NewApiKey:
        """Create an extra key (one per application). The secret is returned once: store it immediately."""
        body: Dict[str, Any] = {"name": name, "notify": notify}
        if description:
            body["description"] = description
        return parse_new_key(self._call("POST", "/v1/keys", json=body))

    def rename_key(self, key_hash: str, name: str) -> dict:
        """Rename a key of your account."""
        return self._call("PATCH", f"/v1/keys/{key_hash}", json={"name": name})

    def revoke_key(self, key_hash: str) -> dict:
        """Revoke a key of your account (the main key cannot be revoked)."""
        return self._call("DELETE", f"/v1/keys/{key_hash}")

    def rotate_key(self, key_hash: str, name: Optional[str] = None, description: Optional[str] = None,
                   notify: bool = True) -> NewApiKey:
        """Replace a key by a new one (history, plan and credit follow). The new secret is returned once."""
        body: Dict[str, Any] = {"notify": notify}
        if name:
            body["name"] = name
        if description:
            body["description"] = description
        return parse_new_key(self._call("POST", f"/v1/keys/{key_hash}/rotate", json=body))

    # ================================================================
    # PLANS AND PAYMENTS
    # ================================================================

    def list_plans(self) -> dict:
        """The official price list: plans, credit packs, quotas (public route; raw API payload)."""
        return self._call("GET", "/v1/billing/plans")

    def get_ledger(self, limit: int = 50) -> List[dict]:
        """The wallet journal: top-ups, bonuses, usage, adjustments (raw API rows)."""
        return self._call("GET", "/v1/billing/ledger", params={"limit": limit}).get("items", [])

    def list_payments(self, limit: int = 50) -> List[dict]:
        """Payment history (raw API rows)."""
        return self._call("GET", "/v1/billing/payments", params={"limit": limit}).get("items", [])

    def quote(self, kind: str, item: str) -> dict:
        """Price of a purchase before paying. ``kind`` is ``"subscription"`` or ``"topup"``; ``item`` a plan
        (``standard``, ``pro``) or a credit pack id (see ``list_plans()``)."""
        return self._call("POST", "/v1/billing/quote", json={"kind": kind, "item": item})

    def create_checkout(self, kind: str, item: str, success_url: str, cancel_url: str,
                        expected_amount_xof: Optional[int] = None) -> dict:
        """Start a payment. Returns ``redirect_url``: open it in a browser to pay. Nothing is charged until the
        payment is completed there. Pass ``expected_amount_xof`` from ``quote()`` to be protected against a
        rate change between the quote and the payment (HTTP 409)."""
        body: Dict[str, Any] = {"kind": kind, "item": item, "success_url": success_url, "cancel_url": cancel_url}
        if expected_amount_xof is not None:
            body["expected_amount_xof"] = expected_amount_xof
        return self._call("POST", "/v1/billing/checkout", json=body)

    # ================================================================
    # REAL TIME (WebSocket)
    # ================================================================

    def realtime(self, timeout: float = 60.0):
        """Open a real-time session (Professional and Enterprise plans). Requires ``pip install
        "lexiafrik[realtime]"``. Use it as a context manager; see ``lexiafrik.realtime.RealtimeSession``."""
        from .realtime import RealtimeSession
        return RealtimeSession(self.api_key, self.base_url, timeout=timeout)

    def health(self) -> dict:
        """Check that the API is up."""
        return self._call("GET", "/health")

    # ================================================================
    # INTERNAL
    # ================================================================

    def _handle_response(self, response: httpx.Response) -> dict:
        """Kept for compatibility: see ``lexiafrik._http.raise_for_response``."""
        return raise_for_response(response)

    def close(self):
        """Close the HTTP connections."""
        self._client.close()
        if self._storage_client is not None:
            self._storage_client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

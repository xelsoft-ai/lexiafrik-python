"""
LexiAfrik SDK — Asynchronous client (asyncio), for web applications and parallel processing.

    import asyncio
    from lexiafrik import AsyncLexiAfrikClient

    async def main():
        async with AsyncLexiAfrikClient() as client:
            results = await asyncio.gather(
                client.transcribe("a.wav", language="wo"),
                client.transcribe("b.wav", language="wo"),
            )
            print([r.text for r in results])

    asyncio.run(main())

It offers the same methods as :class:`lexiafrik.LexiAfrikClient`, as coroutines, with the same automatic
retries and exceptions.
"""

import asyncio
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, AsyncIterator, BinaryIO, Callable, Dict, List, Optional, Union

import httpx

from ._http import RetryPolicy, raise_for_response
from ._parse import (
    normalize_tags, parse_account, parse_dashboard, parse_history, parse_key, parse_languages, parse_new_key,
    parse_result, parse_segment_page,
)
from .auth import DEFAULT_BASE_URL, load_credentials
from .client import _UNSET, _meta_body
from .exceptions import APIError, AudioTooLargeError, AuthenticationError, LexiAfrikError, TranscriptionError
from .models import (
    AccountInfo, ApiKey, FolderItem, Language, NewApiKey, SegmentPage, TranscriptionPage, TranscriptionResult,
    UsageDashboard,
)

_CHUNK = 1024 * 1024


async def _file_chunks(path: Path) -> AsyncIterator[bytes]:
    loop = asyncio.get_event_loop()
    with open(path, "rb") as f:
        while True:
            chunk = await loop.run_in_executor(None, f.read, _CHUNK)
            if not chunk:
                return
            yield chunk


class AsyncLexiAfrikClient:
    """Asynchronous HTTP client for the LexiAfrik API. Same arguments as :class:`LexiAfrikClient`."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 300.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        max_retries: int = 3,
        retry_backoff: float = 0.5,
    ):
        saved = None
        self.api_key = api_key or os.environ.get("LEXIAFRIK_API_KEY")
        if not self.api_key:
            saved = load_credentials()
            self.api_key = saved["api_key"] if saved else None
        if not self.api_key:
            raise AuthenticationError("Missing API key. Pass api_key=, set LEXIAFRIK_API_KEY or run `lexiafrik login`.")
        base_url = (base_url or os.environ.get("LEXIAFRIK_BASE_URL")
                    or (saved or {}).get("base_url") or DEFAULT_BASE_URL)
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-API-Key": self.api_key, "Accept-Language": os.environ.get("LEXIAFRIK_LANG", "en")},
            timeout=timeout, transport=transport,
        )
        self._storage_client: Optional[httpx.AsyncClient] = None  # created on first upload
        self._timeout = timeout
        self._transport = transport
        self._retry = RetryPolicy(max_retries=max_retries, backoff=retry_backoff)
        self._sleep = asyncio.sleep  # replaced in tests

    @property
    def _storage(self) -> httpx.AsyncClient:
        if self._storage_client is None:
            self._storage_client = httpx.AsyncClient(timeout=self._timeout, transport=self._transport)
        return self._storage_client

    # ---------------------------------------------------------------- transport

    async def _send(self, method: str, url: str, **kwargs) -> httpx.Response:
        attempt = 0
        while True:
            try:
                resp = await self._client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                if attempt < self._retry.max_retries and self._retry.retry_exception(method, exc):
                    attempt += 1
                    await self._sleep(self._retry.delay(attempt))
                    continue
                raise APIError(f"Could not reach the LexiAfrik API ({type(exc).__name__}: {exc}).") from exc
            if attempt < self._retry.max_retries and self._retry.retry_status(method, resp.status_code):
                attempt += 1
                await self._sleep(self._retry.delay(attempt, resp))
                continue
            return resp

    async def _call(self, method: str, url: str, **kwargs) -> dict:
        return raise_for_response(await self._send(method, url, **kwargs))

    # ---------------------------------------------------------------- transcription

    async def transcribe(
        self,
        audio: Union[str, Path, bytes, BinaryIO],
        filename: str = "audio.wav",
        language: Optional[str] = None,
        include_segments: bool = False,
        keep_audio: bool = True,
    ) -> TranscriptionResult:
        """Transcribe an audio file (50 MB maximum). See :meth:`LexiAfrikClient.transcribe`."""
        if isinstance(audio, (str, Path)):
            path = Path(audio)
            if not path.is_file():
                raise LexiAfrikError(f"File not found: {audio}")
            filename = path.name
            content = await asyncio.get_event_loop().run_in_executor(None, path.read_bytes)
        elif isinstance(audio, bytes):
            content = audio
        else:
            content = audio.read()
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        form = {"include_segments": str(include_segments).lower(), "keep_audio": str(keep_audio).lower()}
        if language:
            form["language"] = language
        data = await self._call("POST", "/v1/transcribe", files={"file": (filename, content, ctype)}, data=form)
        return parse_result(data, data.get("request_id", ""))

    async def upload(self, file: Union[str, Path], content_type: Optional[str] = None) -> str:
        """Upload a file straight to storage and return its ``upload_key``."""
        path = Path(file)
        if not path.is_file():
            raise LexiAfrikError(f"File not found: {file}")
        ctype = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        size = path.stat().st_size
        slot = await self._call("POST", "/v1/uploads", json={"filename": path.name, "content_type": ctype})
        max_mb = slot.get("max_size_mb")
        if max_mb and size > max_mb * 1024 * 1024:
            raise AudioTooLargeError(f"File of {size / 1024 / 1024:.0f} MB: your plan accepts {max_mb} MB at most.")
        headers = {**(slot.get("headers") or {}), "Content-Length": str(size)}
        try:
            resp = await self._storage.request(slot.get("method", "PUT"), slot["upload_url"],
                                               headers=headers, content=_file_chunks(path))
        except httpx.HTTPError as exc:
            raise APIError(f"File upload failed ({type(exc).__name__}: {exc}).") from exc
        if resp.status_code >= 300:
            raise APIError(f"File upload failed (HTTP {resp.status_code}).", status_code=resp.status_code)
        return slot["upload_key"]

    async def start_transcription(self, url: Optional[str] = None, *, upload_key: Optional[str] = None,
                                  language: Optional[str] = None, title: Optional[str] = None,
                                  keep_audio: bool = True, webhook_url: Optional[str] = None) -> str:
        """Start an asynchronous job and return its ``task_id``."""
        if bool(url) == bool(upload_key):
            raise LexiAfrikError("Provide either url= or upload_key=.")
        payload: Dict[str, Any] = {"keep_audio": keep_audio, "include_segments": True}
        for k, v in (("url", url), ("upload_key", upload_key), ("language", language),
                     ("title", title), ("webhook_url", webhook_url)):
            if v:
                payload[k] = v
        return (await self._call("POST", "/v1/transcribe-url", json=payload))["task_id"]

    async def get_task(self, task_id: str) -> dict:
        """Raw state of a job."""
        return await self._call("GET", f"/v1/tasks/{task_id}")

    async def wait_for_task(self, task_id: str, poll_interval: float = 3.0, job_timeout: float = 3600.0,
                            on_progress: Optional[Callable[[int], None]] = None) -> TranscriptionResult:
        """Wait for a job to finish (``on_progress(n)`` gets the number of segments done)."""
        deadline = time.monotonic() + job_timeout
        while time.monotonic() < deadline:
            resp = await self._send("GET", f"/v1/tasks/{task_id}")
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
            await asyncio.sleep(max(wait, 0.0))
        raise TranscriptionError(f"Timed out after {job_timeout:.0f}s waiting for task '{task_id}'.")

    async def transcribe_url(self, url: Optional[str] = None, *, upload_key: Optional[str] = None,
                             language: Optional[str] = None, title: Optional[str] = None, keep_audio: bool = True,
                             poll_interval: float = 3.0, job_timeout: float = 3600.0,
                             on_progress: Optional[Callable[[int], None]] = None) -> TranscriptionResult:
        """Transcribe a direct link or an uploaded file and wait for the result."""
        task_id = await self.start_transcription(url, upload_key=upload_key, language=language, title=title,
                                                 keep_audio=keep_audio)
        return await self.wait_for_task(task_id, poll_interval, job_timeout, on_progress)

    async def transcribe_large(self, file: Union[str, Path], language: Optional[str] = None,
                               title: Optional[str] = None, keep_audio: bool = True, poll_interval: float = 3.0,
                               job_timeout: float = 3600.0,
                               on_progress: Optional[Callable[[int], None]] = None) -> TranscriptionResult:
        """Upload a large file or a video, run it as a job and wait for the result."""
        path = Path(file)
        key = await self.upload(path)
        return await self.transcribe_url(upload_key=key, language=language, title=title or path.name,
                                         keep_audio=keep_audio, poll_interval=poll_interval,
                                         job_timeout=job_timeout, on_progress=on_progress)

    async def transcribe_folder(
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
        """Transcribe every audio and video file of a folder, ``jobs`` at a time. See
        :meth:`LexiAfrikClient.transcribe_folder`."""
        from . import batch, formats
        root = Path(folder)
        files = batch.find_media(root, recursive)
        if output_format:
            formats.render(TranscriptionResult(request_id="", text=""), output_format)
        want_segments = (output_format or "").lower() in ("srt", "vtt", "json", "")
        sem = asyncio.Semaphore(max(1, int(jobs)))

        async def work(src: Path) -> FolderItem:
            out = batch.output_path_for(src, root, out_dir, output_format) if output_format else None
            if out is not None and skip_existing and out.exists():
                item = FolderItem(path=str(src), status="skipped", output_path=str(out))
            else:
                async with sem:
                    try:
                        big = src.suffix.lower() in batch.VIDEO_EXTENSIONS or src.stat().st_size > batch.DIRECT_MAX_BYTES
                        res = None
                        if not big:
                            try:
                                res = await self.transcribe(src, language=language, include_segments=want_segments,
                                                            keep_audio=keep_audio)
                            except AudioTooLargeError:
                                res = None
                        if res is None:
                            res = await self.transcribe_large(src, language=language, keep_audio=keep_audio)
                        if out is not None:
                            out.parent.mkdir(parents=True, exist_ok=True)
                            out.write_text(formats.render(res, output_format), encoding="utf-8")
                        item = FolderItem(path=str(src), status="success", result=res,
                                          output_path=str(out) if out else None)
                    except Exception as e:  # noqa: BLE001 — one bad file must not stop the batch
                        item = FolderItem(path=str(src), status="error", error=str(e) or type(e).__name__)
            if on_item:
                on_item(item)
            return item

        return list(await asyncio.gather(*(work(f) for f in files)))

    # ---------------------------------------------------------------- languages, account, history

    async def list_languages(self) -> List[Language]:
        return parse_languages(await self._call("GET", "/v1/languages"))

    async def get_account(self) -> AccountInfo:
        return parse_account(await self._call("GET", "/v1/billing/account"))

    get_usage = get_account

    async def get_usage_dashboard(self, period: str = "7d") -> UsageDashboard:
        return parse_dashboard(await self._call("GET", "/v1/usage/dashboard", params={"period": period}))

    async def list_transcriptions(self, page: int = 1, page_size: int = 20,
                                  status: Optional[str] = None) -> TranscriptionPage:
        params: Dict[str, Any] = {"page": page, "page_size": page_size}
        if status:
            params["status"] = status
        return parse_history(await self._call("GET", "/v1/transcriptions", params=params), page, page_size)

    async def get_transcription(self, request_id: str) -> dict:
        return await self._call("GET", f"/v1/transcriptions/{request_id}")

    async def delete_transcription(self, request_id: str) -> None:
        await self._call("DELETE", f"/v1/transcriptions/{request_id}")

    # ---------------------------------------------------------------- segments, corrections, tags

    async def get_segments(self, request_id: str, *, q: Optional[str] = None, offset: int = 0,
                           limit: Optional[int] = None) -> SegmentPage:
        params: Dict[str, Any] = {"offset": offset}
        if limit is not None:
            params["limit"] = limit
        if q:
            params["q"] = q
        return parse_segment_page(
            await self._call("GET", f"/v1/transcriptions/{request_id}/segments", params=params), offset, limit)

    async def update_transcription(self, request_id: str, *, edited_text: Any = _UNSET, tags: Any = _UNSET) -> dict:
        return await self._call("PATCH", f"/v1/transcriptions/{request_id}", json=_meta_body(edited_text, tags))

    async def update_segment(self, request_id: str, segment_id: int, *, edited_text: Any = _UNSET,
                             tags: Any = _UNSET) -> dict:
        return await self._call("PATCH", f"/v1/transcriptions/{request_id}/segments/{segment_id}",
                                json=_meta_body(edited_text, tags))

    async def delete_segment(self, request_id: str, segment_id: int) -> dict:
        return await self._call("DELETE", f"/v1/transcriptions/{request_id}/segments/{segment_id}")

    async def get_audio_url(self, request_id: str, segment_id: Optional[int] = None) -> str:
        path = f"/v1/transcriptions/{request_id}" + (f"/segments/{segment_id}" if segment_id is not None else "")
        return (await self._call("GET", path + "/audio"))["url"]

    # ---------------------------------------------------------------- API keys

    async def list_keys(self) -> List[ApiKey]:
        return [parse_key(k) for k in (await self._call("GET", "/v1/keys")).get("keys", [])]

    async def create_key(self, name: str, description: Optional[str] = None, notify: bool = True) -> NewApiKey:
        body: Dict[str, Any] = {"name": name, "notify": notify}
        if description:
            body["description"] = description
        return parse_new_key(await self._call("POST", "/v1/keys", json=body))

    async def rename_key(self, key_hash: str, name: str) -> dict:
        return await self._call("PATCH", f"/v1/keys/{key_hash}", json={"name": name})

    async def revoke_key(self, key_hash: str) -> dict:
        return await self._call("DELETE", f"/v1/keys/{key_hash}")

    async def rotate_key(self, key_hash: str, name: Optional[str] = None, description: Optional[str] = None,
                         notify: bool = True) -> NewApiKey:
        body: Dict[str, Any] = {"notify": notify}
        if name:
            body["name"] = name
        if description:
            body["description"] = description
        return parse_new_key(await self._call("POST", f"/v1/keys/{key_hash}/rotate", json=body))

    # ---------------------------------------------------------------- plans and payments

    async def list_plans(self) -> dict:
        return await self._call("GET", "/v1/billing/plans")

    async def get_ledger(self, limit: int = 50) -> List[dict]:
        return (await self._call("GET", "/v1/billing/ledger", params={"limit": limit})).get("items", [])

    async def list_payments(self, limit: int = 50) -> List[dict]:
        return (await self._call("GET", "/v1/billing/payments", params={"limit": limit})).get("items", [])

    async def quote(self, kind: str, item: str) -> dict:
        return await self._call("POST", "/v1/billing/quote", json={"kind": kind, "item": item})

    async def create_checkout(self, kind: str, item: str, success_url: str, cancel_url: str,
                              expected_amount_xof: Optional[int] = None) -> dict:
        body: Dict[str, Any] = {"kind": kind, "item": item, "success_url": success_url, "cancel_url": cancel_url}
        if expected_amount_xof is not None:
            body["expected_amount_xof"] = expected_amount_xof
        return await self._call("POST", "/v1/billing/checkout", json=body)

    # ---------------------------------------------------------------- real time

    def realtime(self, timeout: float = 60.0):
        """Open an asynchronous real-time session (Professional and Enterprise plans). Requires
        ``pip install "lexiafrik[realtime]"``. Use it with ``async with``."""
        from .realtime import AsyncRealtimeSession
        return AsyncRealtimeSession(self.api_key, self.base_url, timeout=timeout)

    async def health(self) -> dict:
        return await self._call("GET", "/health")

    # ---------------------------------------------------------------- lifecycle

    async def aclose(self) -> None:
        """Close the HTTP connections."""
        await self._client.aclose()
        if self._storage_client is not None:
            await self._storage_client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()

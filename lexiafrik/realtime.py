"""
LexiAfrik SDK — Real-time transcription over WebSocket (Professional and Enterprise plans).

Install the extra dependency once::

    pip install "lexiafrik[realtime]"

The service works utterance by utterance: you stream the audio of one utterance, then ask for its
transcription; the buffer is emptied and you can continue with the next one.

    from lexiafrik import LexiAfrikClient

    with LexiAfrikClient().realtime() as session:
        for chunk in microphone_chunks():     # bytes of one complete audio file (e.g. WAV), in pieces
            session.send_audio(chunk)
        print(session.transcribe().text)

    # or, for a file:
    with client.realtime() as session:
        print(session.transcribe_file("speech.wav").text)

Async version: ``async with client.realtime() as session:`` on an :class:`AsyncLexiAfrikClient`.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Union
from urllib.parse import quote, urlsplit, urlunsplit

from .exceptions import AuthenticationError, LexiAfrikError, QuotaExceededError

_INSTALL_HINT = 'Real-time transcription needs the "websockets" package: pip install "lexiafrik[realtime]"'
_CHUNK = 64 * 1024


@dataclass
class RealtimeResult:
    """The transcription of one utterance."""
    text: str
    duration_s: float = 0.0
    request_id: Optional[str] = None
    code_switching: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.text


class RealtimeError(LexiAfrikError):
    """The real-time session reported an error."""


def realtime_url(base_url: str, api_key: str) -> str:
    """``https://api.lexiafrik.com`` -> ``wss://api.lexiafrik.com/v1/ws/transcribe?api_key=...``"""
    parts = urlsplit(base_url)
    scheme = "wss" if parts.scheme == "https" else "ws"
    return urlunsplit((scheme, parts.netloc, "/v1/ws/transcribe", f"api_key={quote(api_key, safe='')}", ""))


def _result(msg: Dict[str, Any]) -> RealtimeResult:
    return RealtimeResult(text=msg.get("text") or "", duration_s=float(msg.get("duration_s") or 0.0),
                          request_id=msg.get("request_id"), code_switching=msg.get("code_switching") or {}, raw=msg)


def _opening_error(msg: Dict[str, Any], code: Optional[int]) -> LexiAfrikError:
    detail = msg.get("detail")
    if code == 4001:
        return AuthenticationError("Invalid or revoked API key.", detail)
    if code == 4029:
        return QuotaExceededError("Real-time needs the Professional or Enterprise plan, with quota or credit left.", detail)
    return RealtimeError("The real-time session could not be opened.", detail)


def _close_code(exc: BaseException) -> Optional[int]:
    rcvd = getattr(exc, "rcvd", None)
    return getattr(rcvd, "code", None) if rcvd is not None else getattr(exc, "code", None)


class RealtimeSession:
    """A real-time session (synchronous). Use it as a context manager."""

    def __init__(self, api_key: str, base_url: str, timeout: float = 60.0):
        self._url = realtime_url(base_url, api_key)
        self._timeout = timeout
        self._ws = None
        self._cm = None

    def __enter__(self) -> "RealtimeSession":
        try:
            from websockets.sync.client import connect
        except ImportError as e:
            raise LexiAfrikError(_INSTALL_HINT) from e
        try:
            self._cm = connect(self._url, open_timeout=self._timeout, max_size=None)
            self._ws = self._cm.__enter__()
            msg = json.loads(self._ws.recv(timeout=self._timeout))
        except OSError as e:
            raise RealtimeError(f"Could not open the real-time connection ({type(e).__name__}: {e}).") from e
        if msg.get("type") == "error":
            code = None
            try:
                self._ws.recv(timeout=2)
            except Exception as exc:  # the server closes right after the error: its close code says why
                code = _close_code(exc)
            self.close()
            raise _opening_error(msg, code)
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def send_audio(self, chunk: bytes) -> None:
        """Add a piece of audio to the current utterance."""
        self._ws.send(bytes(chunk))

    def transcribe(self) -> RealtimeResult:
        """Transcribe the audio sent so far, then empty the buffer for the next utterance."""
        self._ws.send("transcribe")
        while True:
            msg = json.loads(self._ws.recv(timeout=self._timeout))
            if msg.get("type") == "transcription":
                return _result(msg)
            if msg.get("type") == "error":
                raise RealtimeError("The server could not transcribe this audio.", msg.get("detail"))

    def reset(self) -> None:
        """Throw away the audio sent so far."""
        self._ws.send("reset")
        while json.loads(self._ws.recv(timeout=self._timeout)).get("type") != "reset":
            pass

    def transcribe_file(self, path: Union[str, Path], chunk_size: int = _CHUNK) -> RealtimeResult:
        """Stream a whole audio file as one utterance and return its transcription."""
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                self.send_audio(chunk)
        return self.transcribe()

    def close(self) -> None:
        ws, cm, self._ws, self._cm = self._ws, self._cm, None, None
        if ws is not None:
            try:
                ws.send("close")
            except Exception:
                pass
        if cm is not None:
            try:
                cm.__exit__(None, None, None)
            except Exception:
                pass


class AsyncRealtimeSession:
    """A real-time session (asyncio). Use it with ``async with``."""

    def __init__(self, api_key: str, base_url: str, timeout: float = 60.0):
        self._url = realtime_url(base_url, api_key)
        self._timeout = timeout
        self._ws = None
        self._cm = None

    async def _recv(self) -> Dict[str, Any]:
        import asyncio
        return json.loads(await asyncio.wait_for(self._ws.recv(), self._timeout))

    async def __aenter__(self) -> "AsyncRealtimeSession":
        try:
            try:
                from websockets.asyncio.client import connect
            except ImportError:  # websockets < 13
                from websockets import connect  # type: ignore
        except ImportError as e:
            raise LexiAfrikError(_INSTALL_HINT) from e
        try:
            self._cm = connect(self._url, open_timeout=self._timeout, max_size=None)
            self._ws = await self._cm.__aenter__()
            msg = await self._recv()
        except OSError as e:
            raise RealtimeError(f"Could not open the real-time connection ({type(e).__name__}: {e}).") from e
        if msg.get("type") == "error":
            code = None
            try:
                import asyncio
                await asyncio.wait_for(self._ws.recv(), 2)
            except Exception as exc:
                code = _close_code(exc)
            await self.aclose()
            raise _opening_error(msg, code)
        return self

    async def __aexit__(self, *args) -> None:
        await self.aclose()

    async def send_audio(self, chunk: bytes) -> None:
        await self._ws.send(bytes(chunk))

    async def transcribe(self) -> RealtimeResult:
        await self._ws.send("transcribe")
        while True:
            msg = await self._recv()
            if msg.get("type") == "transcription":
                return _result(msg)
            if msg.get("type") == "error":
                raise RealtimeError("The server could not transcribe this audio.", msg.get("detail"))

    async def reset(self) -> None:
        await self._ws.send("reset")
        while (await self._recv()).get("type") != "reset":
            pass

    async def transcribe_file(self, path: Union[str, Path], chunk_size: int = _CHUNK) -> RealtimeResult:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                await self.send_audio(chunk)
        return await self.transcribe()

    async def aclose(self) -> None:
        ws, cm, self._ws, self._cm = self._ws, self._cm, None, None
        if ws is not None:
            try:
                await ws.send("close")
            except Exception:
                pass
        if cm is not None:
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                pass

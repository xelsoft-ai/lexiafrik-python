"""Tests of the real-time WebSocket sessions against a local fake server. Skipped without ``websockets``."""

import asyncio
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

os.environ.pop("LEXIAFRIK_API_KEY", None)
os.environ["LEXIAFRIK_CREDENTIALS"] = os.path.join(tempfile.mkdtemp(), "none.json")

try:
    import websockets  # noqa: F401
    from websockets.sync.server import serve as sync_serve
    HAVE_WS = True
except ImportError:  # pragma: no cover
    HAVE_WS = False

from lexiafrik import AsyncLexiAfrikClient, AuthenticationError, LexiAfrikClient, LexiAfrikError, QuotaExceededError  # noqa: E402
from lexiafrik.realtime import RealtimeError, realtime_url  # noqa: E402


class Url(unittest.TestCase):
    def test_scheme_and_key_encoding(self):
        self.assertEqual(realtime_url("https://api.lexiafrik.com", "lx_a b/c"),
                         "wss://api.lexiafrik.com/v1/ws/transcribe?api_key=lx_a%20b%2Fc")
        self.assertTrue(realtime_url("http://127.0.0.1:9", "k").startswith("ws://127.0.0.1:9/v1/ws/transcribe"))


def fake_handler(state):
    """Mimics the service: ready, then buffer audio and answer 'transcribe' / 'reset' / 'close'."""
    def handler(ws):
        query = parse_qs(urlsplit(ws.request.path).query)
        key = query.get("api_key", [""])[0]
        state["key"] = key
        if key == "bad":
            ws.send(json.dumps({"type": "error", "detail": "Clé API invalide."}))
            ws.close(code=4001)
            return
        if key == "free":
            ws.send(json.dumps({"type": "error", "detail": "Offre Professionnel requise."}))
            ws.close(code=4029)
            return
        ws.send(json.dumps({"type": "ready", "max_buffer_mb": 50}))
        buf = bytearray()
        for msg in ws:
            if isinstance(msg, bytes):
                buf.extend(msg)
            elif msg == "transcribe":
                if not buf:
                    ws.send(json.dumps({"type": "error", "detail": "Buffer vide."}))
                    continue
                state["received"] = bytes(buf)
                ws.send(json.dumps({"type": "transcription", "text": "Salaam aleekum", "duration_s": 2.5,
                                    "request_id": "abc12345", "code_switching": {"wolof_ratio": 1.0}}))
                buf.clear()
            elif msg == "reset":
                buf.clear()
                ws.send(json.dumps({"type": "reset"}))
            elif msg == "close":
                return
    return handler


@unittest.skipUnless(HAVE_WS, "websockets is not installed")
class Sync(unittest.TestCase):
    def setUp(self):
        self.state = {}
        self.server = sync_serve(fake_handler(self.state), "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.socket.getsockname()[1]}"

    def tearDown(self):
        self.server.shutdown()

    def client(self, key="good"):
        return LexiAfrikClient(api_key=key, base_url=self.base)

    def test_stream_chunks_then_transcribe(self):
        with self.client().realtime() as s:
            for chunk in (b"RIFF", b"....", b"data"):
                s.send_audio(chunk)
            res = s.transcribe()
        self.assertEqual((res.text, res.duration_s, res.request_id, str(res)),
                         ("Salaam aleekum", 2.5, "abc12345", "Salaam aleekum"))
        self.assertEqual(res.code_switching, {"wolof_ratio": 1.0})
        self.assertEqual((self.state["key"], self.state["received"]), ("good", b"RIFF....data"))

    def test_two_utterances_and_reset(self):
        with self.client().realtime() as s:
            s.send_audio(b"one")
            self.assertEqual(s.transcribe().text, "Salaam aleekum")
            s.send_audio(b"discard me")
            s.reset()
            s.send_audio(b"two")
            s.transcribe()
        self.assertEqual(self.state["received"], b"two")

    def test_transcribe_file(self):
        f = Path(tempfile.mkdtemp()) / "a.wav"
        f.write_bytes(b"x" * 200_000)
        with self.client().realtime() as s:
            res = s.transcribe_file(f, chunk_size=50_000)
        self.assertEqual(res.text, "Salaam aleekum")
        self.assertEqual(len(self.state["received"]), 200_000)

    def test_server_error_becomes_an_exception(self):
        with self.client().realtime() as s:
            with self.assertRaises(RealtimeError) as cm:
                s.transcribe()                                         # empty buffer
        self.assertIn("Buffer vide", str(cm.exception))

    def test_refused_sessions_map_to_the_right_exceptions(self):
        with self.assertRaises(AuthenticationError):
            with self.client("bad").realtime():
                pass
        with self.assertRaises(QuotaExceededError) as cm:
            with self.client("free").realtime():
                pass
        self.assertIn("Professional", str(cm.exception))


@unittest.skipUnless(HAVE_WS, "websockets is not installed")
class Async(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.state = {}
        self.server = sync_serve(fake_handler(self.state), "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.socket.getsockname()[1]}"

    def tearDown(self):
        self.server.shutdown()

    async def test_async_session(self):
        async with AsyncLexiAfrikClient(api_key="good", base_url=self.base) as c:
            async with c.realtime() as s:
                await s.send_audio(b"abc")
                res = await s.transcribe()
        self.assertEqual((res.text, self.state["received"]), ("Salaam aleekum", b"abc"))

    async def test_async_refused(self):
        async with AsyncLexiAfrikClient(api_key="bad", base_url=self.base) as c:
            with self.assertRaises(AuthenticationError):
                async with c.realtime():
                    pass


class WithoutWebsockets(unittest.TestCase):
    def test_helpful_message_when_the_extra_is_missing(self):
        import builtins
        real_import = builtins.__import__

        def fake(name, *a, **k):
            if name.startswith("websockets"):
                raise ImportError("no websockets")
            return real_import(name, *a, **k)

        builtins.__import__ = fake
        try:
            with self.assertRaises(LexiAfrikError) as cm:
                with LexiAfrikClient(api_key="k", base_url="http://127.0.0.1:1").realtime():
                    pass
        finally:
            builtins.__import__ = real_import
        self.assertIn("lexiafrik[realtime]", str(cm.exception))


if __name__ == "__main__":
    unittest.main()

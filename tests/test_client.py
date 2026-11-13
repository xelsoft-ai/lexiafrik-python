"""
SDK tests, with no external network and no real key:
  - errors and short transcription: httpx.MockTransport;
  - large file: local fake HTTP server (real PUT upload, Content-Length, job polling).

    python -m unittest discover -s tests -v
"""

import hashlib
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

os.environ.pop("LEXIAFRIK_API_KEY", None)
os.environ["LEXIAFRIK_CREDENTIALS"] = os.path.join(tempfile.mkdtemp(), "none.json")

from lexiafrik import (  # noqa: E402
    APIError, AudioTooLargeError, AuthenticationError, LexiAfrikClient, LexiAfrikError, NotFoundError,
    QuotaExceededError, RateLimitError, TranscriptionError, UnsupportedFormatError,
)

SYNC_RESPONSE = {
    "success": True, "request_id": "r1", "language": "wo-SN", "full_text": "Salaam aleekum",
    "n_segments": 2, "total_duration_s": 7.5, "timestamp": "2026-11-12T10:00:00Z",
    "segments": [
        {"index": 0, "start_s": 0.0, "end_s": 3.0, "duration_s": 3.0, "text": "Salaam", "inference_time_s": 0.2, "rtf": 0.07},
        {"index": 1, "start_s": 3.2, "end_s": 7.5, "duration_s": 4.3, "text": "aleekum", "inference_time_s": 0.3, "rtf": 0.07,
         "audio_url": "https://x/seg1.wav", "sample_rate": 48000},
    ],
}


def mock_client(handler) -> LexiAfrikClient:
    return LexiAfrikClient(api_key="lx_test", base_url="https://api.test", transport=httpx.MockTransport(handler))


class ShortFile(unittest.TestCase):
    def test_transcribe_sends_options_and_maps_response(self):
        seen = {}

        def handler(req: httpx.Request):
            seen["path"], seen["key"] = req.url.path, req.headers.get("x-api-key")
            seen["body"] = req.content.decode("latin-1")
            return httpx.Response(200, json=SYNC_RESPONSE)

        r = mock_client(handler).transcribe(b"RIFFdata", filename="a.wav", language="wo", include_segments=True)
        self.assertEqual(seen["path"], "/v1/transcribe")
        self.assertEqual(seen["key"], "lx_test")
        for needle in ('name="language"', "wo", 'name="include_segments"', "true", 'name="file"; filename="a.wav"'):
            self.assertIn(needle, seen["body"])
        self.assertEqual((r.text, str(r), r.full_text), ("Salaam aleekum", "Salaam aleekum", "Salaam aleekum"))
        self.assertEqual((r.request_id, r.language, r.duration_s, r.n_segments), ("r1", "wo-SN", 7.5, 2))
        self.assertEqual(r.segments[1].audio_url, "https://x/seg1.wav")
        self.assertEqual(r.segments[1].sample_rate, 48000)
        self.assertEqual(str(r.segments[0]), "[0.0s → 3.0s] Salaam")
        self.assertEqual(r.timestamp.year, 2026)

    def test_language_omitted_by_default(self):
        body = {}
        mock_client(lambda req: (body.update(b=req.content.decode("latin-1")) or httpx.Response(200, json=SYNC_RESPONSE))
                    ).transcribe(b"x")
        self.assertNotIn('name="language"', body["b"])

    def test_missing_file(self):
        with self.assertRaises(LexiAfrikError):
            mock_client(lambda r: httpx.Response(200, json={})).transcribe("/nope/absent.wav")


class Errors(unittest.TestCase):
    CASES = [
        (401, {"detail": "Clé invalide"}, AuthenticationError),
        (403, {"detail": "Interdit"}, AuthenticationError),
        (402, {"detail": "Quota mensuel épuisé"}, QuotaExceededError),
        (404, {"detail": "Task introuvable"}, NotFoundError),
        (413, {"detail": "Fichier trop gros"}, AudioTooLargeError),
        (415, {"detail": "Format non supporté"}, UnsupportedFormatError),
        (422, {"detail": "Langue non supportée : 'xx'"}, TranscriptionError),
        (429, {"detail": "Trop de tentatives"}, RateLimitError),
        (500, {"detail": "Erreur interne"}, APIError),
    ]

    def test_status_to_exception(self):
        for code, body, exc in self.CASES:
            with self.subTest(code=code):
                client = mock_client(lambda req, c=code, b=body: httpx.Response(c, json=b))
                with self.assertRaises(exc) as cm:
                    client.health()
                self.assertIn(body["detail"].split(":")[0], str(cm.exception))

    def test_messages_are_english_and_keep_the_server_text(self):
        client = mock_client(lambda r: httpx.Response(402, json={"detail": "Quota mensuel épuisé"}))
        with self.assertRaises(QuotaExceededError) as cm:
            client.health()
        self.assertEqual(cm.exception.message, "Monthly quota and credit exhausted: top up or change plan.")
        self.assertEqual(cm.exception.detail, "Quota mensuel épuisé")
        self.assertIn("[server: Quota mensuel épuisé]", str(cm.exception))

    def test_announces_english_by_default(self):
        seen = {}

        def handler(req):
            seen["lang"] = req.headers.get("accept-language")
            return httpx.Response(200, json={"status": "ok"})

        mock_client(handler).health()
        self.assertEqual(seen["lang"], "en")

    def test_validation_error_list_is_readable(self):
        client = mock_client(lambda r: httpx.Response(422, json={"detail": [{"msg": "champ requis", "loc": ["body"]}]}))
        with self.assertRaises(TranscriptionError) as cm:
            client.health()
        self.assertIn("champ requis", str(cm.exception))

    def test_api_error_keeps_status(self):
        with self.assertRaises(APIError) as cm:
            mock_client(lambda r: httpx.Response(503, text="down")).health()
        self.assertEqual(cm.exception.status_code, 503)

    def test_no_key(self):
        with self.assertRaises(AuthenticationError) as cm:
            LexiAfrikClient()
        self.assertIn("lexiafrik login", str(cm.exception))


class AccountAndHistory(unittest.TestCase):
    def test_account(self):
        acc = {"plan": "free", "plan_name": "Gratuit", "quota_seconds": 900, "used_seconds": 300.0,
               "quota_remaining_seconds": 600.0, "wallet_usd": 1.4, "wallet_minutes": 20.0,
               "period_end": "2026-12-01T00:00:00+00:00", "wallet_expires_at": None, "features": {"realtime": False}}
        a = mock_client(lambda r: httpx.Response(200, json=acc)).get_account()
        self.assertEqual((a.plan, a.plan_name, a.quota_remaining_minutes, a.available_minutes), ("free", "Gratuit", 10.0, 30.0))

    def test_account_unlimited(self):
        acc = {"plan": "enterprise", "plan_name": "Entreprise", "quota_seconds": None, "used_seconds": 5.0,
               "quota_remaining_seconds": None, "wallet_usd": 0, "wallet_minutes": 0, "features": {}}
        a = mock_client(lambda r: httpx.Response(200, json=acc)).get_usage()
        self.assertIsNone(a.available_minutes)

    def test_languages(self):
        data = {"default": "wo-SN", "languages": [{"code": "wo-SN", "name": "Wolof (Sénégal)", "aliases": ["wo"]}]}
        langs = mock_client(lambda r: httpx.Response(200, json=data)).list_languages()
        self.assertEqual((langs[0].code, langs[0].aliases), ("wo-SN", ["wo"]))

    def test_history_and_delete(self):
        calls = []

        def handler(req: httpx.Request):
            calls.append((req.method, req.url.path, dict(req.url.params)))
            if req.method == "DELETE":
                return httpx.Response(200, json={"deleted": True})
            return httpx.Response(200, json={"items": [
                {"request_id": "a", "status": "success", "text": "t", "source_title": "Titre", "tags": ["x"], "language": "wo-SN"}],
                "total": 41})

        c = mock_client(handler)
        page = c.list_transcriptions(page=2, page_size=10, status="success")
        self.assertEqual((page.total, page.items[0].title, page.items[0].tags), (41, "Titre", ["x"]))
        self.assertEqual(calls[0][2], {"page": "2", "page_size": "10", "status": "success"})
        c.delete_transcription("a")
        self.assertEqual(calls[1][:2], ("DELETE", "/v1/transcriptions/a"))


class FakeServer(BaseHTTPRequestHandler):
    """Mini API: /v1/uploads, PUT storage, /v1/transcribe-url, /v1/tasks/{id} (2 polls in progress, then success)."""
    state = {"polls": 0, "put": None, "payload": None, "headers": None}

    def log_message(self, *a):  # silence
        pass

    def _json(self, code, obj, headers=None):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        base = f"http://127.0.0.1:{self.server.server_port}"
        if self.path == "/v1/uploads":
            self.state["upload_req"] = body
            return self._json(200, {"upload_key": "originals/u/k.mp4", "upload_url": f"{base}/store/k.mp4", "method": "PUT",
                                    "headers": {"Content-Type": body["content_type"]}, "expires_in": 3600, "max_size_mb": 100})
        if self.path == "/v1/transcribe-url":
            self.state["payload"] = body
            return self._json(202, {"task_id": "t1", "status": "processing"})
        self._json(404, {"detail": "?"})

    def do_PUT(self):
        n = int(self.headers.get("Content-Length") or -1)
        data = self.rfile.read(n) if n >= 0 else b""
        self.state["put"] = (n, hashlib.sha256(data).hexdigest(), self.headers.get("X-API-Key"), self.headers.get("Content-Type"))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path == "/v1/tasks/t1":
            self.state["polls"] += 1
            if self.state["polls"] < 3:
                seg = [{"index": 0, "start_s": 0, "end_s": 1, "duration_s": 1, "text": "a"}] * self.state["polls"]
                return self._json(200, {"task_id": "t1", "status": "processing", "segments": seg}, {"Retry-After": "0"})
            return self._json(200, {"task_id": "t1", "status": "success", "full_text": "Texte final", "language": "wo-SN",
                                    "total_duration_s": 120.0, "n_segments": 1, "title": "k.mp4", "audio_url": "https://x/a.m4a",
                                    "segments": [{"index": 0, "start_s": 0, "end_s": 120, "duration_s": 120, "text": "Texte final"}]})
        self._json(404, {"detail": "?"})


class LargeFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeServer)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_transcribe_large_end_to_end(self):
        FakeServer.state.update(polls=0, put=None, payload=None)
        data = os.urandom(3 * 1024 * 1024 + 123)   # plusieurs blocs d'envoi
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "conference.mp4"
            f.write_bytes(data)
            progress = []
            c = LexiAfrikClient(api_key="lx_test", base_url=self.base)
            r = c.transcribe_large(f, language="wo", poll_interval=0, on_progress=progress.append)

        size, digest, key_header, ctype = FakeServer.state["put"]
        self.assertEqual(size, len(data))
        self.assertEqual(digest, hashlib.sha256(data).hexdigest())      # file received intact
        self.assertIsNone(key_header)                                    # the API key is not sent to storage
        self.assertEqual(ctype, "video/mp4")
        self.assertEqual(FakeServer.state["upload_req"], {"filename": "conference.mp4", "content_type": "video/mp4"})
        p = FakeServer.state["payload"]
        self.assertEqual((p["upload_key"], p["language"], p["title"], p["keep_audio"]), ("originals/u/k.mp4", "wo", "conference.mp4", True))
        self.assertNotIn("url", p)
        self.assertEqual(progress, [1, 2])
        self.assertEqual((r.text, r.request_id, r.duration_s, r.audio_url), ("Texte final", "t1", 120.0, "https://x/a.m4a"))

    def test_url_or_key_required(self):
        c = LexiAfrikClient(api_key="lx_test", base_url=self.base)
        with self.assertRaises(LexiAfrikError):
            c.start_transcription()
        with self.assertRaises(LexiAfrikError):
            c.start_transcription("https://x/a.mp3", upload_key="k")

    def test_file_over_plan_limit_is_refused_before_upload(self):
        FakeServer.state["put"] = None
        calls = []

        def handler(req: httpx.Request):
            calls.append(req.url.path)
            return httpx.Response(200, json={"upload_key": "k", "upload_url": "https://s/x", "method": "PUT",
                                             "headers": {}, "expires_in": 60, "max_size_mb": 0.001})

        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "big.wav"
            f.write_bytes(b"0" * 5000)
            with self.assertRaises(AudioTooLargeError):
                mock_client(handler).upload(f)
        self.assertEqual(calls, ["/v1/uploads"])           # aucun envoi vers le stockage

    def test_job_error(self):
        def handler(req: httpx.Request):
            return httpx.Response(200, json={"task_id": "t", "status": "error", "error": "Fichier illisible"})
        with self.assertRaises(TranscriptionError) as cm:
            mock_client(handler).wait_for_task("t", poll_interval=0)
        self.assertIn("illisible", str(cm.exception))

    def test_job_timeout(self):
        def handler(req: httpx.Request):
            return httpx.Response(200, json={"task_id": "t", "status": "processing"})
        with self.assertRaises(TranscriptionError):
            mock_client(handler).wait_for_task("t", poll_interval=0, job_timeout=0.05)


if __name__ == "__main__":
    unittest.main(verbosity=2)

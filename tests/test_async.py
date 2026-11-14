"""Tests of the asynchronous client (httpx.MockTransport: no network, no real key)."""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path

import httpx

os.environ.pop("LEXIAFRIK_API_KEY", None)
os.environ["LEXIAFRIK_CREDENTIALS"] = os.path.join(tempfile.mkdtemp(), "none.json")

from lexiafrik import (  # noqa: E402
    APIError, AsyncLexiAfrikClient, AudioTooLargeError, AuthenticationError, LexiAfrikError, NotFoundError,
    QuotaExceededError, RateLimitError,
)

SYNC = {
    "success": True, "request_id": "r1", "language": "wo-SN", "full_text": "Salaam aleekum", "n_segments": 1,
    "total_duration_s": 3.0,
    "segments": [{"index": 0, "start_s": 0.0, "end_s": 3.0, "duration_s": 3.0, "text": "Salaam aleekum"}],
}


def make(handler, retries=0, sleeps=None):
    c = AsyncLexiAfrikClient(api_key="lx_test", base_url="https://api.test",
                             transport=httpx.MockTransport(handler), max_retries=retries)
    if sleeps is not None:
        async def fake_sleep(s):
            sleeps.append(s)
        c._sleep = fake_sleep
    return c


class AsyncClient(unittest.IsolatedAsyncioTestCase):
    async def test_transcribe_and_formats(self):
        seen = {}

        def handler(req):
            seen["key"], seen["path"], seen["lang"] = (req.headers.get("x-api-key"), req.url.path,
                                                        req.headers.get("accept-language"))
            return httpx.Response(200, json=SYNC)

        async with make(handler) as c:
            res = await c.transcribe(b"abc", filename="a.wav", language="wo", include_segments=True)
        self.assertEqual((res.text, res.language, seen["key"], seen["path"], seen["lang"]),
                         ("Salaam aleekum", "wo-SN", "lx_test", "/v1/transcribe", "en"))
        self.assertIn("00:00:03,000", res.to_srt())

    async def test_parallel_calls(self):
        async with make(lambda r: httpx.Response(200, json=SYNC)) as c:
            results = await asyncio.gather(*(c.transcribe(b"x", filename=f"{i}.wav") for i in range(5)))
        self.assertEqual([r.request_id for r in results], ["r1"] * 5)

    async def test_error_mapping(self):
        cases = [(401, AuthenticationError), (402, QuotaExceededError), (404, NotFoundError),
                 (413, AudioTooLargeError), (500, APIError)]
        for code, exc in cases:
            with self.subTest(code=code):
                async with make(lambda r, c=code: httpx.Response(c, json={"detail": "x"})) as client:
                    with self.assertRaises(exc):
                        await client.health()

    async def test_retries(self):
        calls, sleeps = [], []

        def handler(req):
            calls.append(1)
            if len(calls) < 3:
                return httpx.Response(429, headers={"Retry-After": "1"}, json={"detail": "slow"})
            return httpx.Response(200, json={"status": "ok"})

        async with make(handler, retries=3, sleeps=sleeps) as c:
            self.assertEqual(await c.health(), {"status": "ok"})
        self.assertEqual((len(calls), sleeps), (3, [1.0, 1.0]))

        calls.clear()
        async with make(lambda r: (calls.append(1), httpx.Response(429, json={}))[1], retries=1, sleeps=[]) as c:
            with self.assertRaises(RateLimitError):
                await c.health()
        self.assertEqual(len(calls), 2)

    async def test_post_is_not_retried_after_a_timeout(self):
        calls = []

        def handler(req):
            calls.append(1)
            raise httpx.ReadTimeout("slow")

        async with make(handler, retries=3, sleeps=[]) as c:
            with self.assertRaises(APIError):
                await c.transcribe(b"x", filename="a.wav")
        self.assertEqual(len(calls), 1)

    async def test_upload_and_async_job(self):
        tmp = Path(tempfile.mkdtemp()) / "talk.mp4"
        tmp.write_bytes(b"v" * 3000)
        state = {"polls": 0, "put": 0}

        def handler(req):
            p = req.url.path
            if req.url.host == "storage.test":
                state["put"] = len(req.content)
                return httpx.Response(200)
            if p == "/v1/uploads":
                return httpx.Response(200, json={"upload_url": "https://storage.test/put", "upload_key": "k1",
                                                 "method": "PUT", "headers": {"Content-Type": "video/mp4"}})
            if p == "/v1/transcribe-url":
                self.assertEqual(json.loads(req.content)["upload_key"], "k1")
                return httpx.Response(202, json={"task_id": "t1"})
            state["polls"] += 1
            if state["polls"] < 2:
                return httpx.Response(200, headers={"Retry-After": "0"}, json={"status": "processing", "segments": [{}]})
            return httpx.Response(200, json={"status": "success", "full_text": "Texte", "segments": [],
                                             "total_duration_s": 9.0})

        progress = []
        async with make(handler) as c:
            res = await c.transcribe_large(tmp, language="wo", poll_interval=0, on_progress=progress.append)
        self.assertEqual((res.text, res.request_id, state["put"], progress), ("Texte", "t1", 3000, [1]))

    async def test_folder_with_failures(self):
        tmp = Path(tempfile.mkdtemp())
        for n in ("a.wav", "b.wav", "c.wav"):
            (tmp / n).write_bytes(b"x" * 10)

        def handler(req):
            if b'filename="b.wav"' in req.content:
                return httpx.Response(422, json={"detail": "illisible"})
            return httpx.Response(200, json=SYNC)

        done = []
        async with make(handler) as c:
            items = await c.transcribe_folder(tmp, output_format="srt", jobs=2, on_item=done.append)
        self.assertEqual([(Path(i.path).name, i.status) for i in items],
                         [("a.wav", "success"), ("b.wav", "error"), ("c.wav", "success")])
        self.assertEqual(len(done), 3)
        self.assertTrue((tmp / "a.srt").is_file() and not (tmp / "b.srt").exists())
        async with make(handler) as c:
            again = await c.transcribe_folder(tmp, output_format="srt")
        self.assertEqual([i.status for i in again], ["skipped", "error", "skipped"])

    async def test_segments_keys_usage_billing(self):
        def handler(req):
            p, m = req.url.path, req.method
            if p.endswith("/segments") and m == "GET":
                return httpx.Response(200, json={"total": 1, "items": [{"id": 3, "segment_index": 0, "text": "A",
                                                                         "edited_text": "B"}]})
            if p == "/v1/keys" and m == "POST":
                return httpx.Response(201, json={"api_key": "lx_S", "key_hash": "h", "prefix": "lx_p", "name": "n"})
            if p == "/v1/keys":
                return httpx.Response(200, json={"keys": [{"key_hash": "h", "name": "n", "prefix": "lx_p", "primary": True}]})
            if p.endswith("/usage/dashboard"):
                return httpx.Response(200, json={"period": "7d", "tier": "pro", "today": {}, "month": {},
                                                 "total_transcriptions": 3})
            if p.endswith("/billing/account"):
                return httpx.Response(200, json={"plan": "pro", "plan_name": "Professionnel", "quota_seconds": 72000,
                                                 "used_seconds": 0, "quota_remaining_seconds": 72000,
                                                 "wallet_usd": 0, "wallet_minutes": 0})
            if p.endswith("/audio"):
                return httpx.Response(200, json={"url": "https://x/a"})
            if m == "PATCH":
                return httpx.Response(200, json=json.loads(req.content))
            return httpx.Response(200, json={"items": [{"id": 1}], "plans": []})

        async with make(handler) as c:
            page = await c.get_segments("r1", q="x")
            self.assertEqual((page.total, page.items[0].best_text), (1, "B"))
            self.assertEqual((await c.create_key("n")).api_key, "lx_S")
            self.assertTrue((await c.list_keys())[0].primary)
            self.assertEqual((await c.get_usage_dashboard()).tier, "pro")
            self.assertEqual((await c.get_account()).plan_name, "Professionnel")
            self.assertEqual(await c.get_audio_url("r1"), "https://x/a")
            self.assertEqual(await c.update_transcription("r1", edited_text="T", tags={"a": "b"}),
                             {"edited_text": "T", "tags": [{"key": "a", "value": "b"}]})
            self.assertEqual(await c.get_ledger(), [{"id": 1}])
            with self.assertRaises(LexiAfrikError):
                await c.update_segment("r1", 3)

    async def test_missing_key(self):
        with self.assertRaises(AuthenticationError):
            AsyncLexiAfrikClient()


if __name__ == "__main__":
    unittest.main()

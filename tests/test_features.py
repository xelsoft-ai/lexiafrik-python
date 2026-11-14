"""
Tests of the 2.1 features, with no external network and no real key:
output formats, automatic retries, segments / corrections / tags, API keys, usage and payments,
folder transcription and the command line.
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import httpx

os.environ.pop("LEXIAFRIK_API_KEY", None)
os.environ["LEXIAFRIK_CREDENTIALS"] = os.path.join(tempfile.mkdtemp(), "none.json")

from lexiafrik import (  # noqa: E402
    APIError, AudioTooLargeError, LexiAfrikClient, LexiAfrikError, NewApiKey, QuotaExceededError, RateLimitError,
    SegmentResult, TranscriptionResult, formats,
)
from lexiafrik import batch, cli  # noqa: E402

SYNC = {
    "success": True, "request_id": "r1", "language": "wo-SN", "full_text": "Salaam aleekum", "n_segments": 2,
    "total_duration_s": 7.5,
    "segments": [
        {"index": 0, "start_s": 0.0, "end_s": 3.0, "duration_s": 3.0, "text": "Salaam"},
        {"index": 1, "start_s": 3.2, "end_s": 3725.5, "duration_s": 3722.3, "text": "aleekum"},
    ],
}


def client_for(handler, retries=0, sleeps=None):
    c = LexiAfrikClient(api_key="lx_test", base_url="https://api.test", transport=httpx.MockTransport(handler),
                        max_retries=retries)
    if sleeps is not None:
        c._sleep = sleeps.append
    return c


class Formats(unittest.TestCase):
    def setUp(self):
        self.res = TranscriptionResult(
            request_id="r1", text="Salaam aleekum", duration_s=7.5,
            segments=[SegmentResult(0, 0.0, 3.0, 3.0, "Salaam"), SegmentResult(1, 3.2, 3725.5, 3722.3, "aleekum")])

    def test_srt(self):
        self.assertEqual(
            formats.to_srt(self.res),
            "1\n00:00:00,000 --> 00:00:03,000\nSalaam\n\n2\n00:00:03,200 --> 01:02:05,500\naleekum\n")

    def test_vtt(self):
        out = self.res.to_vtt()
        self.assertTrue(out.startswith("WEBVTT\n"))
        self.assertIn("00:00:03.200 --> 01:02:05.500\naleekum", out)

    def test_text_and_json(self):
        self.assertEqual(self.res.to_text(), "Salaam aleekum\n")
        data = json.loads(self.res.to_json())
        self.assertEqual((data["request_id"], data["language"], len(data["segments"])), ("r1", None, 2))
        self.assertEqual(data["segments"][1]["end_s"], 3725.5)

    def test_without_segments_the_whole_text_is_one_cue(self):
        res = TranscriptionResult(request_id="r", text="Texte entier", duration_s=12.0)
        self.assertEqual(formats.to_srt(res), "1\n00:00:00,000 --> 00:00:12,000\nTexte entier\n")
        self.assertEqual(formats.to_srt(TranscriptionResult(request_id="r", text="")), "")

    def test_unknown_format(self):
        with self.assertRaises(ValueError):
            formats.render(self.res, "docx")
        self.assertEqual(formats.render(self.res, ".SRT"), formats.to_srt(self.res))


class Retries(unittest.TestCase):
    def test_429_then_success_waits_for_retry_after(self):
        calls, sleeps = [], []

        def handler(req):
            calls.append(1)
            if len(calls) < 3:
                return httpx.Response(429, headers={"Retry-After": "2"}, json={"detail": "slow"})
            return httpx.Response(200, json={"status": "ok"})

        self.assertEqual(client_for(handler, retries=3, sleeps=sleeps).health(), {"status": "ok"})
        self.assertEqual((len(calls), sleeps), (3, [2.0, 2.0]))

    def test_retry_after_is_capped(self):
        calls, sleeps = [], []

        def handler(req):
            calls.append(1)
            return httpx.Response(429, headers={"Retry-After": "9999"}) if len(calls) == 1 else httpx.Response(200, json={})

        client_for(handler, retries=2, sleeps=sleeps).health()
        self.assertEqual(sleeps, [30.0])

    def test_gives_up_after_max_retries(self):
        calls, sleeps = [], []

        def handler(req):
            calls.append(1)
            return httpx.Response(429, json={"detail": "slow"})

        with self.assertRaises(RateLimitError):
            client_for(handler, retries=2, sleeps=sleeps).health()
        self.assertEqual((len(calls), len(sleeps)), (3, 2))

    def test_post_is_retried_on_503_but_not_on_500(self):
        for status, expected in ((503, 2), (500, 1)):
            with self.subTest(status=status):
                calls = []

                def handler(req, s=status):
                    calls.append(1)
                    return httpx.Response(s, json={"detail": "x"}) if len(calls) == 1 else httpx.Response(200, json=SYNC)

                c = client_for(handler, retries=3, sleeps=[])
                try:
                    c.transcribe(b"abc", filename="a.wav")
                except APIError:
                    pass
                self.assertEqual(len(calls), expected)

    def test_get_is_retried_on_502(self):
        calls = []

        def handler(req):
            calls.append(1)
            return httpx.Response(502) if len(calls) < 3 else httpx.Response(200, json={"status": "ok"})

        self.assertEqual(client_for(handler, retries=3, sleeps=[]).health(), {"status": "ok"})

    def test_post_is_retried_after_a_connection_error_only_when_never_sent(self):
        for exc, expected in ((httpx.ConnectError("refused"), 2), (httpx.ReadTimeout("slow"), 1)):
            with self.subTest(exc=type(exc).__name__):
                calls = []

                def handler(req, e=exc):
                    calls.append(1)
                    if len(calls) == 1:
                        raise e
                    return httpx.Response(200, json=SYNC)

                c = client_for(handler, retries=3, sleeps=[])
                try:
                    c.transcribe(b"abc", filename="a.wav")
                except APIError:
                    pass
                self.assertEqual(len(calls), expected)

    def test_network_failure_becomes_an_sdk_error(self):
        def handler(req):
            raise httpx.ConnectError("no route")

        with self.assertRaises(APIError) as cm:
            client_for(handler, retries=1, sleeps=[]).health()
        self.assertIn("Could not reach", str(cm.exception))

    def test_retries_can_be_disabled(self):
        calls = []

        def handler(req):
            calls.append(1)
            return httpx.Response(503, json={"detail": "x"})

        with self.assertRaises(APIError):
            client_for(handler, retries=0).health()
        self.assertEqual(len(calls), 1)


class SegmentsAndCorrections(unittest.TestCase):
    def test_get_segments_with_search(self):
        seen = {}

        def handler(req):
            seen["path"], seen["q"] = req.url.path, dict(req.url.params)
            return httpx.Response(200, json={"total": 2, "items": [
                {"id": 11, "segment_index": 0, "start_s": 0, "end_s": 2, "text": "Salaam", "edited_text": "Salam",
                 "tags": [{"key": "topic", "value": "x"}], "has_audio": True, "audio_url": "https://x/a.wav",
                 "cs_languages": ["wolof"]},
                {"id": 12, "segment_index": 1, "start_s": 2, "end_s": 4, "text": "Bonjour"}]})

        page = client_for(handler).get_segments("r1", q="wolof", offset=5, limit=2)
        self.assertEqual((seen["path"], seen["q"]), ("/v1/transcriptions/r1/segments", {"offset": "5", "limit": "2", "q": "wolof"}))
        self.assertEqual((page.total, page.items[0].best_text, page.items[1].best_text), (2, "Salam", "Bonjour"))
        self.assertEqual((page.items[0].tags, page.items[0].languages), ([{"key": "topic", "value": "x"}], ["wolof"]))

    def test_update_text_and_tags_bodies(self):
        bodies = []

        def handler(req):
            bodies.append((req.method, req.url.path, json.loads(req.content)))
            return httpx.Response(200, json={"request_id": "r1"})

        c = client_for(handler)
        c.update_transcription("r1", edited_text="Texte corrigé", tags={"topic": "interview", "lang": "wo"})
        c.update_transcription("r1", edited_text=None)                       # clears the correction
        c.update_segment("r1", 11, tags=[{"key": "k", "value": "v"}])
        c.update_transcription("r1", tags={})                                # clears all tags
        self.assertEqual(bodies[0], ("PATCH", "/v1/transcriptions/r1",
                                     {"edited_text": "Texte corrigé",
                                      "tags": [{"key": "topic", "value": "interview"}, {"key": "lang", "value": "wo"}]}))
        self.assertEqual(bodies[1][2], {"edited_text": None})                # null is sent, tags are left alone
        self.assertEqual(bodies[2], ("PATCH", "/v1/transcriptions/r1/segments/11", {"tags": [{"key": "k", "value": "v"}]}))
        self.assertEqual(bodies[3][2], {"tags": []})

    def test_nothing_to_update_is_an_error(self):
        with self.assertRaises(LexiAfrikError):
            client_for(lambda r: httpx.Response(200, json={})).update_transcription("r1")

    def test_audio_urls_and_delete_segment(self):
        paths = []

        def handler(req):
            paths.append((req.method, req.url.path))
            return httpx.Response(200, json={"url": "https://x/audio.m4a", "expires_in": 3600})

        c = client_for(handler)
        self.assertEqual(c.get_audio_url("r1"), "https://x/audio.m4a")
        c.get_audio_url("r1", segment_id=7)
        c.delete_segment("r1", 7)
        self.assertEqual(paths, [("GET", "/v1/transcriptions/r1/audio"),
                                 ("GET", "/v1/transcriptions/r1/segments/7/audio"),
                                 ("DELETE", "/v1/transcriptions/r1/segments/7")])


class KeysUsagePayments(unittest.TestCase):
    def test_keys(self):
        calls = []

        def handler(req):
            body = json.loads(req.content) if req.content else None
            calls.append((req.method, req.url.path, body))
            if req.method == "GET":
                return httpx.Response(200, json={"keys": [
                    {"key_hash": "h1", "name": "main", "prefix": "lx_aaaa", "tier": "pro", "active": True,
                     "primary": True, "current": True, "last_used_at": "2026-11-13T10:00:00Z"},
                    {"key_hash": "h2", "name": "app", "prefix": "lx_bbbb", "active": False}]})
            if req.method in ("POST",):
                return httpx.Response(201, json={"api_key": "lx_SECRET", "key_hash": "h3", "prefix": "lx_cccc",
                                                 "name": "ci", "tier": "pro"})
            return httpx.Response(200, json={"key_hash": "h2"})

        c = client_for(handler)
        keys = c.list_keys()
        self.assertEqual((keys[0].primary, keys[0].current, keys[1].active, keys[1].name), (True, True, False, "app"))
        new = c.create_key("ci", description="CI", notify=False)
        self.assertIsInstance(new, NewApiKey)
        self.assertEqual(new.api_key, "lx_SECRET")
        self.assertNotIn("lx_SECRET", repr(new))                              # never printed by accident
        c.rename_key("h2", "renamed")
        c.revoke_key("h2")
        c.rotate_key("h2", name="n2")
        self.assertEqual(calls[1], ("POST", "/v1/keys", {"name": "ci", "notify": False, "description": "CI"}))
        self.assertEqual(calls[2], ("PATCH", "/v1/keys/h2", {"name": "renamed"}))
        self.assertEqual(calls[3][:2], ("DELETE", "/v1/keys/h2"))
        self.assertEqual(calls[4], ("POST", "/v1/keys/h2/rotate", {"notify": True, "name": "n2"}))

    def test_usage_and_billing(self):
        seen = []

        def handler(req):
            seen.append((req.method, req.url.path, dict(req.url.params), json.loads(req.content) if req.content else None))
            p = req.url.path
            if p.endswith("/usage/dashboard"):
                return httpx.Response(200, json={"period": "30d", "tier": "pro", "today": {"requests": 2, "audio_seconds": 90},
                                                 "month": {"requests": 10, "audio_seconds": 600}, "total_transcriptions": 41,
                                                 "languages": {"wolof": 0.9}, "by_key": []})
            if p.endswith("/billing/ledger") or p.endswith("/billing/payments"):
                return httpx.Response(200, json={"items": [{"id": 1}]})
            if p.endswith("/billing/plans"):
                return httpx.Response(200, json={"plans": [{"id": "standard"}]})
            if p.endswith("/billing/quote"):
                return httpx.Response(200, json={"amount_xof": 9600})
            return httpx.Response(200, json={"redirect_url": "https://pay/x", "payment_id": "LX-1"})

        c = client_for(handler)
        u = c.get_usage_dashboard("30d")
        self.assertEqual((u.tier, u.today["requests"], u.total_transcriptions, u.languages["wolof"]), ("pro", 2, 41, 0.9))
        self.assertEqual(c.get_ledger(10), [{"id": 1}])
        self.assertEqual(c.list_payments(5), [{"id": 1}])
        self.assertEqual(c.list_plans()["plans"][0]["id"], "standard")
        self.assertEqual(c.quote("subscription", "standard")["amount_xof"], 9600)
        out = c.create_checkout("topup", "essentiel", "https://s", "https://c", expected_amount_xof=3000)
        self.assertEqual(out["redirect_url"], "https://pay/x")
        self.assertEqual(seen[0][2], {"period": "30d"})
        self.assertEqual(seen[-1][3], {"kind": "topup", "item": "essentiel", "success_url": "https://s",
                                       "cancel_url": "https://c", "expected_amount_xof": 3000})


class Folder(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for name in ("a.wav", "b.mp3", "notes.txt", ".hidden.wav", "sub/c.m4a"):
            f = self.tmp / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"x" * 100)

    def handler(self, fail_for=None):
        seen = []

        def handler(req):
            seen.append(req.url.path)
            if req.url.path == "/v1/transcribe":
                body = req.content.decode("latin-1")
                if fail_for and fail_for in body:
                    return httpx.Response(422, json={"detail": "illisible"})
                return httpx.Response(200, json=SYNC)
            return httpx.Response(404, json={"detail": "?"})

        return handler, seen

    def test_find_media(self):
        names = [p.name for p in batch.find_media(self.tmp)]
        self.assertEqual(names, ["a.wav", "b.mp3"])                         # no .txt, no hidden file, no sub-folder
        self.assertEqual([p.name for p in batch.find_media(self.tmp, recursive=True)], ["a.wav", "b.mp3", "c.m4a"])
        self.assertEqual(batch.find_media(self.tmp / "a.wav"), [self.tmp / "a.wav"])
        with self.assertRaises(LexiAfrikError):
            batch.find_media(self.tmp / "nope")

    def test_writes_one_file_per_input_and_keeps_subfolders(self):
        out = self.tmp / "out"
        h, _ = self.handler()
        items = client_for(h).transcribe_folder(self.tmp, output_format="srt", out_dir=out, recursive=True, jobs=2)
        self.assertEqual([i.status for i in items], ["success"] * 3)
        self.assertTrue((out / "a.srt").is_file() and (out / "sub" / "c.srt").is_file())
        self.assertIn("-->", (out / "a.srt").read_text(encoding="utf-8"))

    def test_one_failure_does_not_stop_the_others_and_skip_existing_resumes(self):
        h, seen = self.handler(fail_for='filename="b.mp3"')
        c = client_for(h)
        items = c.transcribe_folder(self.tmp, output_format="txt", jobs=1)
        self.assertEqual([(Path(i.path).name, i.status) for i in items], [("a.wav", "success"), ("b.mp3", "error")])
        self.assertIn("illisible", items[1].error)
        self.assertTrue((self.tmp / "a.txt").is_file() and not (self.tmp / "b.txt").exists())
        before = len(seen)
        again = c.transcribe_folder(self.tmp, output_format="txt", jobs=1)
        self.assertEqual([i.status for i in again], ["skipped", "error"])    # a.txt exists: not sent again
        self.assertEqual(len(seen) - before, 1)

    def test_too_large_for_the_direct_route_falls_back_to_the_async_route(self):
        calls = []

        def handler(req):
            calls.append(req.url.path)
            if req.url.path == "/v1/transcribe":
                return httpx.Response(413, json={"detail": "trop gros"})
            if req.url.path == "/v1/uploads":
                return httpx.Response(200, json={"upload_url": "https://storage.test/put", "upload_key": "k1",
                                                 "method": "PUT", "headers": {}})
            if req.url.host == "storage.test":
                return httpx.Response(200)
            if req.url.path == "/v1/transcribe-url":
                return httpx.Response(202, json={"task_id": "t1"})
            return httpx.Response(200, json={"task_id": "t1", "status": "success", "full_text": "Texte", "segments": [],
                                             "total_duration_s": 5.0})

        items = client_for(handler).transcribe_folder(self.tmp / "a.wav", output_format="txt")
        self.assertEqual(items[0].status, "success")
        self.assertIn("/v1/transcribe-url", calls)
        self.assertEqual((self.tmp / "a.txt").read_text(encoding="utf-8"), "Texte\n")

    def test_invalid_format_is_refused_before_any_call(self):
        h, seen = self.handler()
        with self.assertRaises(ValueError):
            client_for(h).transcribe_folder(self.tmp, output_format="docx")
        self.assertEqual(seen, [])


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "a.wav").write_bytes(b"x" * 50)
        (self.tmp / "b.wav").write_bytes(b"y" * 50)

    def run_cli(self, argv, handler):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv, client_factory=lambda: client_for(handler))
        return code, out.getvalue(), err.getvalue()

    @staticmethod
    def ok(req):
        return httpx.Response(200, json=SYNC)

    def test_single_file_prints_to_the_screen(self):
        code, out, _ = self.run_cli(["transcribe", str(self.tmp / "a.wav"), "-f", "srt"], self.ok)
        self.assertEqual(code, 0)
        self.assertIn("00:00:00,000 --> 00:00:03,000\nSalaam", out)
        code, out, _ = self.run_cli(["transcribe", str(self.tmp / "a.wav")], self.ok)
        self.assertEqual(out, "Salaam aleekum\n")

    def test_language_and_no_keep_audio_are_sent(self):
        seen = {}

        def handler(req):
            seen["body"] = req.content.decode("latin-1")
            return httpx.Response(200, json=SYNC)

        self.run_cli(["transcribe", str(self.tmp / "a.wav"), "-l", "ha", "--no-keep-audio"], handler)
        self.assertIn('name="language"\r\n\r\nha', seen["body"])
        self.assertIn('name="keep_audio"\r\n\r\nfalse', seen["body"])

    def test_folder_writes_files_and_reports_progress(self):
        code, out, err = self.run_cli(["transcribe", str(self.tmp), "-f", "vtt", "-o", str(self.tmp / "out")], self.ok)
        self.assertEqual((code, out), (0, ""))
        self.assertTrue((self.tmp / "out" / "a.vtt").is_file() and (self.tmp / "out" / "b.vtt").is_file())
        self.assertIn("2 transcribed, 0 skipped, 0 failed", err)

    def test_failure_gives_a_non_zero_exit_code(self):
        def handler(req):
            return httpx.Response(402, json={"detail": "épuisé"})

        code, _, err = self.run_cli(["transcribe", str(self.tmp), "-w"], handler)
        self.assertEqual(code, 1)
        self.assertIn("FAILED", err)
        code, _, err = self.run_cli(["transcribe", str(self.tmp / "a.wav")], handler)
        self.assertEqual(code, 1)
        self.assertIn("Monthly quota and credit exhausted", err)

    def test_bad_format_and_empty_folder(self):
        code, _, err = self.run_cli(["transcribe", str(self.tmp / "a.wav"), "-f", "docx"], self.ok)
        self.assertEqual(code, 1)
        self.assertIn("Unknown format", err)
        empty = Path(tempfile.mkdtemp())
        code, _, err = self.run_cli(["transcribe", str(empty)], self.ok)
        self.assertEqual(code, 1)
        self.assertIn("No audio or video files", err)

    def test_info_commands(self):
        def handler(req):
            p = req.url.path
            if p == "/v1/languages":
                return httpx.Response(200, json={"languages": [{"code": "wo-SN", "name": "Wolof (Senegal)"}]})
            if p == "/v1/billing/account":
                return httpx.Response(200, json={"plan": "standard", "plan_name": "Standard", "quota_seconds": 18000,
                                                 "used_seconds": 600, "quota_remaining_seconds": 17400,
                                                 "wallet_usd": 1.5, "wallet_minutes": 21.4, "period_end": "2026-12-13T00:00:00Z"})
            if p == "/v1/keys":
                return httpx.Response(200, json={"keys": [{"key_hash": "abcdef1234567890", "name": "main", "prefix": "lx_abc",
                                                           "primary": True, "current": True}]})
            return httpx.Response(200, json={"items": [], "total": 0})

        code, out, _ = self.run_cli(["languages"], handler)
        self.assertIn("wo-SN", out)
        code, out, _ = self.run_cli(["account"], handler)
        self.assertIn("Plan: Standard", out)
        self.assertIn("290.0 min left of 300 min", out)
        code, out, _ = self.run_cli(["keys", "list"], handler)
        self.assertIn("main", out)
        self.assertIn("main current", out)

    def test_keys_revoke_resolves_a_prefix_and_refuses_ambiguity(self):
        calls = []

        def handler(req):
            calls.append((req.method, req.url.path))
            if req.method == "GET":
                return httpx.Response(200, json={"keys": [
                    {"key_hash": "aaa111", "name": "one", "prefix": "lx_aa", "primary": True},
                    {"key_hash": "aab222", "name": "two", "prefix": "lx_ab"}]})
            return httpx.Response(200, json={})

        code, out, _ = self.run_cli(["keys", "revoke", "aab"], handler)
        self.assertEqual((code, ("DELETE", "/v1/keys/aab222") in calls), (0, True))
        code, _, err = self.run_cli(["keys", "revoke", "aa"], handler)       # matches both hashes
        self.assertEqual(code, 1)
        self.assertIn("Several keys", err)


if __name__ == "__main__":
    unittest.main()

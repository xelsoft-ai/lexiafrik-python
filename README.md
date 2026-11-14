# LexiAfrik Python SDK

Official Python SDK and command line for the [LexiAfrik API](https://docs.lexiafrik.com): speech-to-text for
Wolof and 30+ other African languages. Full documentation: **https://docs.lexiafrik.com**

🇫🇷 [Version française](https://github.com/xelsoft-ai/lexiafrik-python/blob/main/README.fr.md)

## Installation

```bash
pip install lexiafrik                  # SDK + command line
pip install "lexiafrik[realtime]"      # + real-time transcription (WebSocket)
```

Python 3.8 or newer.

## Command line

```bash
lexiafrik login                                # connect this terminal (no password)
lexiafrik transcribe talk.wav -l wo            # print the text
lexiafrik transcribe talk.mp4 -f srt -w        # write talk.srt next to the video
lexiafrik transcribe interviews/ -r -f vtt -o subtitles/ -j 3    # a whole folder, 3 files at a time
lexiafrik languages | account | usage | history
lexiafrik keys list | create NAME | revoke HASH | rotate HASH
lexiafrik logout                               # delete credentials, revoke this terminal's key
```

`transcribe` accepts files and folders. One file prints to the screen; several files, a folder, `-w` or `-o`
write one file per input (`txt`, `srt`, `vtt` or `json`) and show progress. A file whose output already exists is
skipped, so an interrupted run can simply be started again (`--overwrite` to redo them). One failing file never
stops the others, and the exit code is non-zero if any failed. Short audio files use the direct route; large files
and videos are uploaded and processed automatically.

`lexiafrik login` needs no password and no key to copy: you sign in on lexiafrik.com, check the code shown in the
terminal and approve. An API key dedicated to this terminal is created on your account and saved in
`~/.lexiafrik/credentials.json` (readable by you only). Revoke it any time from **lexiafrik.com > API keys**.

Key lookup order: the `api_key=` argument, the `LEXIAFRIK_API_KEY` environment variable, then the file saved by
`lexiafrik login`. On a server or in CI, create a key on the website and use the environment variable.

## Python

```python
from lexiafrik import LexiAfrikClient

client = LexiAfrikClient()

# Short file (50 MB maximum): immediate response
result = client.transcribe("speech.wav", language="wo", include_segments=True)
print(result.text)
open("speech.srt", "w", encoding="utf-8").write(result.to_srt())   # also to_vtt(), to_text(), to_json()

# Large file or video: direct upload, asynchronous job, wait for the result
result = client.transcribe_large("conference.mp4", language="wo",
                                 on_progress=lambda n: print(n, "segments"))

# Direct link to an audio or video file
result = client.transcribe_url("https://example.com/recording.mp3")

# A whole folder, 3 files at a time, one .srt per file
for item in client.transcribe_folder("interviews/", output_format="srt", jobs=3, recursive=True):
    print(item.status, item.path, item.error or "")
```

### Segments, corrections and tags

```python
page = client.get_segments(result.request_id, q="wolof")           # search text, corrections, tags, language
for seg in page.items:
    print(seg.start_s, seg.best_text)                              # corrected text when there is one

client.update_segment(result.request_id, page.items[0].id, edited_text="Salaam aleekum")
client.update_transcription(result.request_id, tags={"topic": "interview"})
client.update_transcription(result.request_id, edited_text=None)   # remove the correction
url = client.get_audio_url(result.request_id)                      # temporary link to the audio
```

### Account, usage, API keys, payments

```python
print(client.get_account().available_minutes, "minutes available")
print(client.get_usage_dashboard("30d").month)

key = client.create_key("my-app")           # the secret is shown once: key.api_key
client.list_keys(); client.rotate_key(key.key_hash); client.revoke_key(key.key_hash)

quote = client.quote("subscription", "standard")                   # price before paying
pay = client.create_checkout("subscription", "standard", "https://app/ok", "https://app/cancel",
                             expected_amount_xof=quote["amount_xof"])
print(pay["redirect_url"])                                         # open it to pay; nothing is charged before
```

Team management is not available with an API key (it needs a signed-in session on lexiafrik.com). To work with a
team's data, use one of the team's API keys.

### Asynchronous client

```python
import asyncio
from lexiafrik import AsyncLexiAfrikClient

async def main():
    async with AsyncLexiAfrikClient() as client:
        results = await asyncio.gather(client.transcribe("a.wav", language="wo"),
                                       client.transcribe("b.wav", language="wo"))
        print([r.text for r in results])

asyncio.run(main())
```

It offers the same methods as `LexiAfrikClient`, as coroutines.

### Real time (Professional and Enterprise plans)

```python
with client.realtime() as session:                  # needs: pip install "lexiafrik[realtime]"
    session.send_audio(first_chunk)                 # pieces of one audio file (e.g. WAV)
    session.send_audio(second_chunk)
    print(session.transcribe().text)                # then the next utterance...

with client.realtime() as session:
    print(session.transcribe_file("speech.wav").text)
```

The service works utterance by utterance: you stream the audio of one utterance, then ask for its transcription.
Use `async with client.realtime()` on the asynchronous client.

Links to streaming platforms (YouTube, TikTok…) are not accepted: provide a direct link or upload the file.

## Automatic retries

Network errors, HTTP 429 (honoring `Retry-After`) and 503 are retried up to 3 times with an increasing delay
(`LexiAfrikClient(max_retries=0)` turns it off). A request that creates something (a transcription, a key, a payment)
is never repeated after a timeout or a gateway error, because it may already have been processed and billed.

## Error handling

```python
from lexiafrik import LexiAfrikClient, AuthenticationError, QuotaExceededError, LexiAfrikError

try:
    result = client.transcribe("audio.wav")
except AuthenticationError:
    print("Invalid key: run `lexiafrik login` again")
except QuotaExceededError:
    print("Monthly quota and credit exhausted")
except LexiAfrikError as e:
    print(e)            # English message; e.detail holds the server's own text, if any
```

Exceptions: `AuthenticationError` (401/403), `QuotaExceededError` (402), `NotFoundError` (404),
`AudioTooLargeError` (413), `UnsupportedFormatError` (415), `TranscriptionError` (422),
`RateLimitError` (429), `APIError` (5xx and network failures).

## Environment variables

| Variable | Purpose |
|---|---|
| `LEXIAFRIK_API_KEY` | API key (takes priority over the saved file). |
| `LEXIAFRIK_BASE_URL` | Another API address (tests). Default: `https://api.lexiafrik.com`. |
| `LEXIAFRIK_CREDENTIALS` | Another location for the credentials file. |
| `LEXIAFRIK_LANG` | Preferred language of server messages, sent as `Accept-Language` (default: `en`). |

## Migrating

**From 2.0:** nothing breaks; everything new is additive. **From 1.x:** a single result type
(`TranscriptionResult`) for every mode, `get_usage()` returns the account (plan, monthly quota, credit) rather than
daily limits, and the `model`, `n_tokens` and `rtf` result fields no longer exist.

## Tests

```bash
pip install httpx websockets pytest
python -m pytest tests
```

No external network and no real key needed (the real-time tests are skipped without `websockets`).

## Get an API key

Create an account on [lexiafrik.com](https://lexiafrik.com), or run `lexiafrik login`.

## Releasing

Maintainers: see [RELEASING.md](RELEASING.md) and [CHANGELOG.md](CHANGELOG.md).

## License

MIT — see [LICENSE](LICENSE).

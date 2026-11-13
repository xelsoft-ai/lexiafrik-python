# LexiAfrik Python SDK

Official Python SDK and command line for the [LexiAfrik API](https://docs.lexiafrik.com): speech-to-text for
Wolof and 30+ other African languages. Full documentation: **https://docs.lexiafrik.com**

🇫🇷 [Version française](https://github.com/xelsoft-ai/lexiafrik-python/blob/main/README.fr.md)

## Installation

```bash
pip install lexiafrik
```

Python 3.8 or newer.

## Sign in from the terminal

```bash
lexiafrik login      # prints a code, opens your browser, saves a key
lexiafrik whoami     # the saved key and its plan
lexiafrik logout     # deletes the credentials and revokes this terminal's key
```

`lexiafrik login` needs no password and no key to copy: you sign in on lexiafrik.com, check the code shown
in the terminal and approve. An API key dedicated to this terminal is created on your account and saved in
`~/.lexiafrik/credentials.json` (readable by you only). You can revoke it at any time from
**lexiafrik.com > API keys**.

Key lookup order: the `api_key=` argument, the `LEXIAFRIK_API_KEY` environment variable, then the file saved
by `lexiafrik login`. On a server or in CI, create a key on the website and use the environment variable.

## Usage

```python
from lexiafrik import LexiAfrikClient

client = LexiAfrikClient()

# Short file (50 MB maximum): immediate response
result = client.transcribe("speech.wav", language="wo", include_segments=True)
print(result.text)
for seg in result.segments:
    print(seg)                    # [0.4s → 6.1s] First segment.

# Large file or video: direct upload, asynchronous job, wait for the result
result = client.transcribe_large("conference.mp4", language="wo",
                                 on_progress=lambda n: print(n, "segments"))

# Direct link to an audio or video file
result = client.transcribe_url("https://example.com/recording.mp3")

# Languages, account, history
print([l.code for l in client.list_languages()])
print(client.get_account().available_minutes, "minutes available")
for t in client.list_transcriptions(page_size=5).items:
    print(t.request_id, t.status)
```

Links to streaming platforms (YouTube, TikTok…) are not accepted: provide a direct link or upload the file.

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
`RateLimitError` (429), `APIError` (5xx).

## Environment variables

| Variable | Purpose |
|---|---|
| `LEXIAFRIK_API_KEY` | API key (takes priority over the saved file). |
| `LEXIAFRIK_BASE_URL` | Another API address (tests). Default: `https://api.lexiafrik.com`. |
| `LEXIAFRIK_CREDENTIALS` | Another location for the credentials file. |
| `LEXIAFRIK_LANG` | Preferred language of server messages, sent as `Accept-Language` (default: `en`). |

## Migrating from version 1

SDK 2.0 follows the current API: a single result type (`TranscriptionResult`) for every mode, `get_usage()`
returns the account (plan, monthly quota, credit) rather than daily limits, and the `model`, `n_tokens`
and `rtf` fields of the result no longer exist.

## Tests

```bash
python -m unittest discover -s tests -v
```

No external network and no real key needed.

## Get an API key

Create an account on [lexiafrik.com](https://lexiafrik.com), or run `lexiafrik login`.

## License

MIT — see [LICENSE](LICENSE).

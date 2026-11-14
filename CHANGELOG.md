# Changelog

All notable changes to the `lexiafrik` package. Format based on [Keep a Changelog](https://keepachangelog.com);
versions follow [semantic versioning](https://semver.org).

## [2.1.0] — 2026-11-14

### Added
- **Command line:** `lexiafrik transcribe FILE_OR_FOLDER` with `txt`, `srt`, `vtt` and `json` output, folders
  (`-r`), parallel files (`-j`), resume (`--overwrite` to redo), plus `languages`, `account`, `usage`, `history`
  and `keys list | create | revoke | rotate`.
- **Output formats:** `result.to_text() / to_srt() / to_vtt() / to_json()` and the `lexiafrik.formats` module.
- **`AsyncLexiAfrikClient`:** the same methods as coroutines.
- **Automatic retries** (network errors, 429 with `Retry-After`, 503; 500/502/504 for safe methods only);
  requests that create something are never repeated after a timeout. `max_retries=` to tune or disable.
- **Segments, corrections and tags:** `get_segments`, `update_transcription`, `update_segment`, `delete_segment`,
  `get_audio_url`.
- **API keys:** `list_keys`, `create_key`, `rename_key`, `revoke_key`, `rotate_key`.
- **Usage and payments:** `get_usage_dashboard`, `list_plans`, `get_ledger`, `list_payments`, `quote`,
  `create_checkout`.
- **Real time (WebSocket):** `client.realtime()` on both clients; install with `pip install "lexiafrik[realtime]"`.
- **Folders:** `transcribe_folder()` and `lexiafrik.batch` (one failing file never stops the others).

### Changed
- A network failure now raises `APIError` ("Could not reach the LexiAfrik API") instead of a raw `httpx` error.
- The storage HTTP client is created on first upload (faster start-up).

## [2.0.0] — 2026-11-13

First public release on PyPI.

### Added
- `lexiafrik login | logout | whoami`: sign in a terminal without a password (device-code flow); the key is
  created on your account and can be revoked from lexiafrik.com.
- `LexiAfrikClient`: `transcribe`, `transcribe_large`, `transcribe_url`, `upload`, `start_transcription`,
  `wait_for_task`, `list_languages`, `get_account`, `list_transcriptions`, `get_transcription`,
  `delete_transcription`, `health`.
- Exceptions per HTTP status; the server's own text is kept in `exception.detail`.
- Environment variables `LEXIAFRIK_API_KEY`, `LEXIAFRIK_BASE_URL`, `LEXIAFRIK_CREDENTIALS`, `LEXIAFRIK_LANG`.

### Changed
- Everything user-facing is in English (messages, help, documentation); French README kept as `README.fr.md`.
- One result type (`TranscriptionResult`) for every mode; `get_usage()` returns the account (plan, monthly
  quota, credit) instead of daily limits; the `model`, `n_tokens` and `rtf` result fields were removed.

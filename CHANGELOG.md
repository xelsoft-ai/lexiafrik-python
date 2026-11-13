# Changelog

All notable changes to the `lexiafrik` package. Format based on [Keep a Changelog](https://keepachangelog.com);
versions follow [semantic versioning](https://semver.org).

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

"""LexiAfrik SDK — command line.

    lexiafrik login | logout | whoami
    lexiafrik transcribe FILE_OR_FOLDER [...]  [-l wo] [-f txt|srt|vtt|json] [-o DIR] [-r] [-j 3]
    lexiafrik languages | account | usage | history | keys
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, List, Optional

import httpx

from . import __version__, batch, formats
from .auth import DEFAULT_BASE_URL, clear_credentials, credentials_path, load_credentials, login
from .exceptions import LexiAfrikError


def _client(factory: Optional[Callable]):
    if factory:
        return factory()
    from .client import LexiAfrikClient
    return LexiAfrikClient()


def _login(args, factory=None) -> int:
    login(base_url=args.base_url, client_name=args.name, open_browser=not args.no_browser)
    return 0


def _logout(args, factory=None) -> int:
    creds = load_credentials()
    if not creds:
        print("No saved credentials.")
        return 0
    if not args.keep_key and creds.get("key_hash"):
        # Revoke this terminal's key on the LexiAfrik side (best effort: the file is deleted regardless).
        try:
            r = httpx.delete(f"{creds.get('base_url', DEFAULT_BASE_URL)}/v1/keys/{creds['key_hash']}",
                             headers={"X-API-Key": creds["api_key"]}, timeout=15)
            print("Key revoked." if r.status_code < 300 else
                  "The key could not be revoked; revoke it from lexiafrik.com > API keys.")
        except httpx.HTTPError:
            print("API unreachable: revoke the key from lexiafrik.com > API keys.")
    clear_credentials()
    print(f"Credentials deleted ({credentials_path()}).")
    return 0


def _whoami(_args, factory=None) -> int:
    creds = load_credentials()
    if not creds:
        print("Not signed in. Run `lexiafrik login`.")
        return 1
    r = httpx.get(f"{creds.get('base_url', DEFAULT_BASE_URL)}/v1/whoami",
                  headers={"X-API-Key": creds["api_key"]}, timeout=15)
    if r.status_code != 200:
        print("Invalid or revoked key. Run `lexiafrik login` again.")
        return 1
    who = r.json()
    print(f"Key: {creds.get('name', '')} ({creds.get('prefix', '')}…)  Plan: {who.get('tier', '?')}")
    return 0


# ── transcribe ──────────────────────────────────────────────────────────────

def _transcribe(args, factory=None) -> int:
    fmt = args.format.lower()
    if fmt not in formats.FORMATS:
        raise LexiAfrikError(f"Unknown format {fmt!r}: choose one of {', '.join(formats.FORMATS)}.")
    sources: List[Path] = []
    roots = {}
    for target in args.paths:
        found = batch.find_media(target, args.recursive)
        if not found:
            print(f"No audio or video files in {target}", file=sys.stderr)
        for f in found:
            sources.append(f)
            roots[f] = Path(target)
    if not sources:
        return 1

    client = _client(factory)
    single_to_stdout = len(sources) == 1 and not args.out_dir and not args.write
    if single_to_stdout:
        res = batch.transcribe_one(client, sources[0], args.language, not args.no_keep_audio,
                                   want_segments=fmt in ("srt", "vtt", "json"))
        sys.stdout.write(formats.render(res, fmt))
        return 0

    # Several files (or --write / -o): each transcription goes to a file; progress on stderr.
    done = {"n": 0}
    total = len(sources)

    def show(item):
        done["n"] += 1
        mark = {"success": "ok", "skipped": "skipped", "error": "FAILED"}[item.status]
        extra = item.output_path or item.error or ""
        print(f"[{done['n']}/{total}] {mark}  {item.path}  {extra}", file=sys.stderr)

    items = []
    # Group by root so that sub-folders are kept under --out-dir.
    by_root = {}
    for f in sources:
        by_root.setdefault(roots[f], []).append(f)
    for root, files in by_root.items():
        items += batch.transcribe_files(
            client, files, language=args.language, output_format=fmt, out_dir=args.out_dir, root=root,
            skip_existing=not args.overwrite, jobs=args.jobs, keep_audio=not args.no_keep_audio, on_item=show)
    ok = sum(1 for i in items if i.status == "success")
    skipped = sum(1 for i in items if i.status == "skipped")
    failed = [i for i in items if i.status == "error"]
    print(f"{ok} transcribed, {skipped} skipped, {len(failed)} failed.", file=sys.stderr)
    return 1 if failed else 0


# ── account, languages, history, keys ───────────────────────────────────────

def _languages(args, factory=None) -> int:
    for lang in _client(factory).list_languages():
        print(f"{lang.code:<10} {lang.name}")
    return 0


def _account(args, factory=None) -> int:
    a = _client(factory).get_account()
    print(f"Plan: {a.plan_name} ({a.plan})")
    if a.quota_seconds is None:
        print("Monthly quota: unlimited")
    else:
        print(f"Monthly quota: {a.quota_remaining_minutes} min left of {round(a.quota_seconds / 60)} min")
    print(f"Credit: {a.wallet_usd:.2f} USD ({a.wallet_minutes:.0f} min)")
    if a.period_end:
        print(f"Period ends: {a.period_end[:10]}")
    return 0


def _usage(args, factory=None) -> int:
    u = _client(factory).get_usage_dashboard(args.period)
    print(f"Plan: {u.tier}   Transcriptions: {u.total_transcriptions}")
    print(f"Today: {u.today.get('requests', 0)} requests, {round((u.today.get('audio_seconds') or 0) / 60, 1)} min")
    print(f"This month: {u.month.get('requests', 0)} requests, {round((u.month.get('audio_seconds') or 0) / 60, 1)} min")
    return 0


def _history(args, factory=None) -> int:
    client = _client(factory)
    if args.id:
        print(json.dumps(client.get_transcription(args.id), ensure_ascii=False, indent=2, default=str))
        return 0
    page = client.list_transcriptions(page=args.page, page_size=args.size, status=args.status)
    for t in page.items:
        print(f"{t.request_id}  {t.status:<10} {(t.timestamp or '')[:16]}  {(t.title or (t.text or '')[:50])}")
    print(f"-- page {page.page}, {page.total} in total", file=sys.stderr)
    return 0


def _keys(args, factory=None) -> int:
    client = _client(factory)
    if args.action == "list":
        for k in client.list_keys():
            flags = " ".join(f for f, on in (("main", k.primary), ("current", k.current), ("revoked", not k.active)) if on)
            print(f"{k.prefix:<12} {k.name:<28} {k.key_hash[:12]}  {flags}")
        return 0
    if args.action == "create":
        if not args.name:
            raise LexiAfrikError("Give the new key a name: lexiafrik keys create NAME")
        k = client.create_key(args.name)
        print(f"Key created: {k.name} ({k.prefix}…)")
        print(f"Secret (shown once, store it now): {k.api_key}")
        return 0
    if not args.name:
        raise LexiAfrikError(f"Give the key hash (see `lexiafrik keys list`): lexiafrik keys {args.action} HASH")
    target = _resolve_key(client, args.name)
    if args.action == "revoke":
        client.revoke_key(target)
        print("Key revoked.")
    elif args.action == "rotate":
        k = client.rotate_key(target)
        print(f"Key replaced: {k.name} ({k.prefix}…)")
        print(f"Secret (shown once, store it now): {k.api_key}")
    return 0


def _resolve_key(client, ref: str) -> str:
    """Accept a full hash, a hash prefix or a key prefix."""
    matches = [k.key_hash for k in client.list_keys()
               if k.key_hash.startswith(ref) or (k.prefix and k.prefix.startswith(ref))]
    if len(matches) != 1:
        raise LexiAfrikError(f"{'No key' if not matches else 'Several keys'} match {ref!r}: see `lexiafrik keys list`.")
    return matches[0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lexiafrik", description="LexiAfrik - speech-to-text for African languages")
    parser.add_argument("--version", action="version", version=f"lexiafrik {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("login", help="connect this terminal to your account (no password)")
    p.add_argument("--no-browser", action="store_true", help="print the link without opening the browser")
    p.add_argument("--name", help="name of this terminal (shown when you approve it)")
    p.add_argument("--base-url", help=f"API URL (default: {DEFAULT_BASE_URL})")
    p.set_defaults(func=_login)

    p = sub.add_parser("logout", help="delete saved credentials and revoke this terminal's key")
    p.add_argument("--keep-key", action="store_true", help="do not revoke the key on the LexiAfrik side")
    p.set_defaults(func=_logout)

    p = sub.add_parser("whoami", help="show the saved key and its plan")
    p.set_defaults(func=_whoami)

    p = sub.add_parser(
        "transcribe", help="transcribe audio or video files, or whole folders",
        description="Transcribe audio/video files. One file prints to the screen; several files, a folder, "
                    "or -o/--write save one file per input next to it (or under -o).")
    p.add_argument("paths", nargs="+", metavar="FILE_OR_FOLDER")
    p.add_argument("-l", "--language", help="language code, e.g. wo, fr, ha (see `lexiafrik languages`; default: Wolof)")
    p.add_argument("-f", "--format", default="txt", help="txt, srt, vtt or json (default: txt)")
    p.add_argument("-o", "--out-dir", help="write the results under this folder (created if needed)")
    p.add_argument("-w", "--write", action="store_true", help="write the result next to the source file instead of printing")
    p.add_argument("-r", "--recursive", action="store_true", help="include sub-folders")
    p.add_argument("-j", "--jobs", type=int, default=2, help="files processed at the same time (default: 2)")
    p.add_argument("--overwrite", action="store_true", help="transcribe again files whose output already exists")
    p.add_argument("--no-keep-audio", action="store_true", help="keep only the text, not the audio, on LexiAfrik")
    p.set_defaults(func=_transcribe)

    p = sub.add_parser("languages", help="list the available languages")
    p.set_defaults(func=_languages)

    p = sub.add_parser("account", help="plan, remaining quota and credit")
    p.set_defaults(func=_account)

    p = sub.add_parser("usage", help="usage today and this month")
    p.add_argument("--period", default="7d", choices=["7d", "30d", "month"])
    p.set_defaults(func=_usage)

    p = sub.add_parser("history", help="list your transcriptions, or show one with --id")
    p.add_argument("--id", help="show the details of one transcription")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--size", type=int, default=20)
    p.add_argument("--status", choices=["success", "error", "processing"])
    p.set_defaults(func=_history)

    p = sub.add_parser("keys", help="manage your API keys")
    p.add_argument("action", choices=["list", "create", "revoke", "rotate"])
    p.add_argument("name", nargs="?", help="name of the new key (create) or hash/prefix of the key (revoke, rotate)")
    p.set_defaults(func=_keys)
    return parser


def main(argv=None, *, client_factory: Optional[Callable] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args, client_factory)
    except LexiAfrikError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())

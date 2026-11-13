"""LexiAfrik SDK — command line: ``lexiafrik login | logout | whoami``."""

import argparse
import sys

import httpx

from . import __version__
from .auth import DEFAULT_BASE_URL, clear_credentials, credentials_path, load_credentials, login
from .exceptions import LexiAfrikError


def _login(args) -> int:
    login(base_url=args.base_url, client_name=args.name, open_browser=not args.no_browser)
    return 0


def _logout(args) -> int:
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


def _whoami(_args) -> int:
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


def main(argv=None) -> int:
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

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except LexiAfrikError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())

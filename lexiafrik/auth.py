"""
LexiAfrik SDK — Sign in a terminal without a password (device-code flow, RFC 8628).

    from lexiafrik.auth import login
    login()                      # prints a code, opens the browser, saves the key

The API key is created on your account when you approve, then saved in
``~/.lexiafrik/credentials.json`` (readable by you only). ``LexiAfrikClient()`` finds it
afterwards without any parameter. It stays revocable from lexiafrik.com > API keys.
"""

import json
import os
import platform
import socket
import time
import webbrowser
from pathlib import Path
from typing import Callable, Optional

import httpx

from .exceptions import AuthenticationError, LexiAfrikError

DEFAULT_BASE_URL = "https://api.lexiafrik.com"


def credentials_path() -> Path:
    """Credentials file (set LEXIAFRIK_CREDENTIALS to move it)."""
    override = os.environ.get("LEXIAFRIK_CREDENTIALS")
    return Path(override) if override else Path.home() / ".lexiafrik" / "credentials.json"


def load_credentials() -> Optional[dict]:
    try:
        data = json.loads(credentials_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("api_key") else None


def save_credentials(data: dict) -> Path:
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    # Created directly as 0600: the key is never readable by other users.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


def clear_credentials() -> bool:
    try:
        credentials_path().unlink()
        return True
    except FileNotFoundError:
        return False


def default_client_name() -> str:
    try:
        host = socket.gethostname()
    except OSError:
        host = "terminal"
    return f"{host} ({platform.system() or 'CLI'})"[:60]


def login(
    base_url: Optional[str] = None,
    client_name: Optional[str] = None,
    open_browser: bool = True,
    echo: Callable[[str], None] = print,
    save: bool = True,
    timeout: float = 30.0,
) -> dict:
    """
    Connect this terminal to your LexiAfrik account.

    Returns:
        ``{"api_key", "key_hash", "prefix", "name", "base_url"}`` (saved to disk when ``save``).

    Raises:
        AuthenticationError: sign-in denied in the browser.
        LexiAfrikError: code expired or API unreachable.
    """
    base = (base_url or os.environ.get("LEXIAFRIK_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    with httpx.Client(base_url=base, timeout=timeout) as http:
        try:
            r = http.post("/v1/auth/device", json={"client_name": client_name or default_client_name()})
        except httpx.HTTPError as e:
            raise LexiAfrikError(f"API unreachable ({base}): {e}") from e
        if r.status_code == 429:
            raise LexiAfrikError("Too many attempts. Try again in a few minutes.")
        if r.status_code != 200:
            raise LexiAfrikError(f"Could not start the sign-in (HTTP {r.status_code}).")
        d = r.json()

        url = d["verification_uri_complete"]
        echo("")
        echo("To connect this terminal, open:")
        echo(f"  {url}")
        echo("")
        echo(f"Confirmation code: {d['user_code']}")
        echo("(only approve if you just ran this command)")
        echo("")
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:  # no browser (server, SSH): the URL stays displayed
                pass
        echo("Waiting for your approval…")

        interval = max(1, int(d.get("interval", 5)))
        deadline = time.monotonic() + int(d.get("expires_in", 600))
        while time.monotonic() < deadline:
            time.sleep(interval)
            try:
                r = http.post("/v1/auth/device/token", json={"device_code": d["device_code"]})
            except httpx.HTTPError:
                continue  # transient network failure
            if r.status_code == 200:
                creds = {**r.json(), "base_url": base}
                if save:
                    path = save_credentials(creds)
                    echo(f"Signed in. Key '{creds['name']}' saved to {path}")
                return creds
            is_json = r.headers.get("content-type", "").startswith("application/json")
            err = (r.json() if is_json else {}).get("error")
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                interval += 5
                continue
            if err == "access_denied":
                raise AuthenticationError("Sign-in denied in the browser.")
            if err == "expired_token":
                raise LexiAfrikError("The code has expired. Run `lexiafrik login` again.")
            raise LexiAfrikError(f"Sign-in failed ({err or r.status_code}).")
    raise LexiAfrikError("The code has expired. Run `lexiafrik login` again.")

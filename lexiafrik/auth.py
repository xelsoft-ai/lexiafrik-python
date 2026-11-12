"""
LexiAfrik SDK — Connexion d'un terminal sans mot de passe (flux « device code », RFC 8628).

    from lexiafrik.auth import login
    login()                      # affiche un code, ouvre le navigateur, enregistre la clé

La clé API est créée sur votre compte à l'approbation, puis enregistrée dans
``~/.lexiafrik/credentials.json`` (lisible par vous seul). ``LexiAfrikClient()`` la
retrouve ensuite sans paramètre. Elle reste révocable depuis lexiafrik.com > Clés API.
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
    """Fichier d'identifiants (LEXIAFRIK_CREDENTIALS pour le déplacer)."""
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
    # Création directe en 0600 : la clé n'est jamais lisible par les autres utilisateurs.
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
    Connecte ce terminal à votre compte LexiAfrik.

    Returns:
        ``{"api_key", "key_hash", "prefix", "name", "base_url"}`` (enregistré sur disque si ``save``).

    Raises:
        AuthenticationError: connexion refusée dans le navigateur.
        LexiAfrikError: code expiré ou API injoignable.
    """
    base = (base_url or os.environ.get("LEXIAFRIK_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    with httpx.Client(base_url=base, timeout=timeout) as http:
        try:
            r = http.post("/v1/auth/device", json={"client_name": client_name or default_client_name()})
        except httpx.HTTPError as e:
            raise LexiAfrikError(f"API injoignable ({base}) : {e}") from e
        if r.status_code == 429:
            raise LexiAfrikError("Trop de tentatives. Réessayez dans quelques minutes.")
        if r.status_code != 200:
            raise LexiAfrikError(f"Impossible de démarrer la connexion (HTTP {r.status_code}).")
        d = r.json()

        url = d["verification_uri_complete"]
        echo("")
        echo("Pour connecter ce terminal, ouvrez :")
        echo(f"  {url}")
        echo("")
        echo(f"Code de confirmation : {d['user_code']}")
        echo("(n'approuvez que si vous venez de lancer cette commande)")
        echo("")
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:  # navigateur absent (serveur, SSH) : l'URL reste affichée
                pass
        echo("En attente de votre approbation…")

        interval = max(1, int(d.get("interval", 5)))
        deadline = time.monotonic() + int(d.get("expires_in", 600))
        while time.monotonic() < deadline:
            time.sleep(interval)
            try:
                r = http.post("/v1/auth/device/token", json={"device_code": d["device_code"]})
            except httpx.HTTPError:
                continue  # coupure réseau passagère
            if r.status_code == 200:
                creds = {**r.json(), "base_url": base}
                if save:
                    path = save_credentials(creds)
                    echo(f"Connecté. Clé « {creds['name']} » enregistrée dans {path}")
                return creds
            is_json = r.headers.get("content-type", "").startswith("application/json")
            err = (r.json() if is_json else {}).get("error")
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                interval += 5
                continue
            if err == "access_denied":
                raise AuthenticationError("Connexion refusée dans le navigateur.")
            if err == "expired_token":
                raise LexiAfrikError("Le code a expiré. Relancez `lexiafrik login`.")
            raise LexiAfrikError(f"Connexion impossible ({err or r.status_code}).")
    raise LexiAfrikError("Le code a expiré. Relancez `lexiafrik login`.")

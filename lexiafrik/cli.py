"""LexiAfrik SDK — ligne de commande : ``lexiafrik login | logout | whoami``."""

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
        print("Aucun identifiant enregistré.")
        return 0
    if not args.keep_key and creds.get("key_hash"):
        # Révoque la clé de ce terminal côté LexiAfrik (au mieux : le fichier est effacé quoi qu'il arrive).
        try:
            r = httpx.delete(f"{creds.get('base_url', DEFAULT_BASE_URL)}/v1/keys/{creds['key_hash']}",
                             headers={"X-API-Key": creds["api_key"]}, timeout=15)
            print("Clé révoquée." if r.status_code < 300 else
                  "La clé n'a pas pu être révoquée ; révoquez-la depuis lexiafrik.com > Clés API.")
        except httpx.HTTPError:
            print("API injoignable : révoquez la clé depuis lexiafrik.com > Clés API.")
    clear_credentials()
    print(f"Identifiants supprimés ({credentials_path()}).")
    return 0


def _whoami(_args) -> int:
    creds = load_credentials()
    if not creds:
        print("Non connecté. Lancez `lexiafrik login`.")
        return 1
    r = httpx.get(f"{creds.get('base_url', DEFAULT_BASE_URL)}/v1/whoami",
                  headers={"X-API-Key": creds["api_key"]}, timeout=15)
    if r.status_code != 200:
        print("Clé invalide ou révoquée. Relancez `lexiafrik login`.")
        return 1
    who = r.json()
    print(f"Clé : {creds.get('name', '')} ({creds.get('prefix', '')}…)  Offre : {who.get('tier', '?')}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="lexiafrik", description="LexiAfrik — transcription vocale")
    parser.add_argument("--version", action="version", version=f"lexiafrik {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("login", help="connecter ce terminal à votre compte (sans mot de passe)")
    p.add_argument("--no-browser", action="store_true", help="afficher le lien sans ouvrir le navigateur")
    p.add_argument("--name", help="nom de ce terminal (affiché lors de l'approbation)")
    p.add_argument("--base-url", help=f"URL de l'API (défaut : {DEFAULT_BASE_URL})")
    p.set_defaults(func=_login)

    p = sub.add_parser("logout", help="supprimer les identifiants et révoquer la clé de ce terminal")
    p.add_argument("--keep-key", action="store_true", help="ne pas révoquer la clé côté LexiAfrik")
    p.set_defaults(func=_logout)

    p = sub.add_parser("whoami", help="afficher la clé enregistrée et son offre")
    p.set_defaults(func=_whoami)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except LexiAfrikError as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrompu.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())

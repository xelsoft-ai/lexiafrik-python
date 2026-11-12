# LexiAfrik Python SDK

SDK Python officiel pour l'[API LexiAfrik](https://docs.lexiafrik.com) — transcription vocale du wolof
et d'autres langues africaines. Documentation complète : **https://docs.lexiafrik.com**

## Installation

```bash
pip install lexiafrik
```

Python 3.8 ou plus récent.

## Se connecter depuis le terminal

```bash
lexiafrik login      # affiche un code, ouvre le navigateur, enregistre une clé
lexiafrik whoami     # clé enregistrée et offre
lexiafrik logout     # supprime les identifiants et révoque la clé de ce terminal
```

`lexiafrik login` n'utilise ni mot de passe ni clé à copier : vous vous connectez sur
lexiafrik.com, vérifiez le code affiché dans le terminal et approuvez. Une clé API dédiée à ce
terminal est créée sur votre compte et enregistrée dans `~/.lexiafrik/credentials.json` (lisible
par vous seul). Vous pouvez la révoquer à tout moment depuis **lexiafrik.com > Clés API**.

Ordre de recherche de la clé : paramètre `api_key=`, variable `LEXIAFRIK_API_KEY`, puis le fichier
enregistré par `lexiafrik login`. Sur un serveur ou en CI, créez plutôt une clé sur le site et
utilisez la variable d'environnement.

## Usage

```python
from lexiafrik import LexiAfrikClient

client = LexiAfrikClient()

# Fichier court (50 Mo maximum) : réponse immédiate
result = client.transcribe("discours.wav", language="wo", include_segments=True)
print(result.text)
for seg in result.segments:
    print(seg)                    # [0.4s → 6.1s] Premier segment.

# Gros fichier ou vidéo : envoi direct, job asynchrone, attente du résultat
result = client.transcribe_large("conference.mp4", language="wo",
                                 on_progress=lambda n: print(n, "segments"))

# Lien direct vers un fichier audio ou vidéo
result = client.transcribe_url("https://exemple.com/enregistrement.mp3")

# Langues, compte, historique
print([l.code for l in client.list_languages()])
print(client.get_account().available_minutes, "min disponibles")
for t in client.list_transcriptions(page_size=5).items:
    print(t.request_id, t.status)
```

Les liens de plateformes de streaming (YouTube, TikTok…) ne sont pas acceptés : fournissez un lien
direct ou envoyez le fichier.

## Gestion des erreurs

```python
from lexiafrik import LexiAfrikClient, AuthenticationError, QuotaExceededError, LexiAfrikError

try:
    result = client.transcribe("audio.wav")
except AuthenticationError:
    print("Clé invalide : relancez `lexiafrik login`")
except QuotaExceededError:
    print("Quota mensuel et crédit épuisés")
except LexiAfrikError as e:
    print(e)
```

Exceptions : `AuthenticationError` (401/403), `QuotaExceededError` (402), `NotFoundError` (404),
`AudioTooLargeError` (413), `UnsupportedFormatError` (415), `TranscriptionError` (422),
`RateLimitError` (429), `APIError` (5xx).

## Variables d'environnement

| Variable | Rôle |
|---|---|
| `LEXIAFRIK_API_KEY` | Clé API (prioritaire sur le fichier enregistré). |
| `LEXIAFRIK_BASE_URL` | Autre adresse d'API (tests). Défaut : `https://api.lexiafrik.com`. |
| `LEXIAFRIK_CREDENTIALS` | Autre emplacement du fichier d'identifiants. |

## Migration depuis la version 1

Le SDK 2.0 suit l'API actuelle : un seul type de résultat (`TranscriptionResult`) pour tous les modes,
`get_usage()` renvoie le compte (offre, quota mensuel, crédit) et non plus des limites journalières,
les champs `model`, `n_tokens` et `rtf` du résultat n'existent plus.

## Tests

```bash
python -m unittest discover -s tests -v
```

Sans réseau externe ni clé réelle.

## Obtenir une clé API

Créez un compte sur [lexiafrik.com](https://lexiafrik.com), ou lancez `lexiafrik login`.

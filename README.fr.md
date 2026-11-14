# LexiAfrik Python SDK (français)

🇬🇧 [English version](https://github.com/xelsoft-ai/lexiafrik-python/blob/main/README.md)

SDK Python et ligne de commande officiels pour l'[API LexiAfrik](https://docs.lexiafrik.com) : transcription vocale
du wolof et de plus de 30 langues africaines. Documentation complète : **https://docs.lexiafrik.com**

## Installation

```bash
pip install lexiafrik                  # SDK + commande
pip install "lexiafrik[realtime]"      # + transcription en temps réel (WebSocket)
```

Python 3.8 ou plus récent.

## Ligne de commande

```bash
lexiafrik login                                # connecter ce terminal (sans mot de passe)
lexiafrik transcribe discours.wav -l wo        # affiche le texte
lexiafrik transcribe conference.mp4 -f srt -w  # écrit conference.srt à côté de la vidéo
lexiafrik transcribe entretiens/ -r -f vtt -o sous-titres/ -j 3   # un dossier entier, 3 fichiers à la fois
lexiafrik languages | account | usage | history
lexiafrik keys list | create NOM | revoke HASH | rotate HASH
lexiafrik logout                               # supprime les identifiants, révoque la clé de ce terminal
```

`transcribe` accepte des fichiers et des dossiers. Un fichier s'affiche à l'écran ; plusieurs fichiers, un dossier,
`-w` ou `-o` écrivent un fichier par source (`txt`, `srt`, `vtt` ou `json`) et montrent la progression. Un fichier
dont le résultat existe déjà est ignoré, donc une exécution interrompue se relance simplement (`--overwrite` pour
tout refaire). Un fichier en échec n'arrête pas les autres, et le code de sortie est non nul si l'un a échoué.

`lexiafrik login` n'utilise ni mot de passe ni clé à copier : vous vous connectez sur lexiafrik.com, vérifiez le
code affiché dans le terminal et approuvez. Une clé API dédiée à ce terminal est créée sur votre compte et
enregistrée dans `~/.lexiafrik/credentials.json` (lisible par vous seul). Révocable à tout moment depuis
**lexiafrik.com > Clés API**.

Ordre de recherche de la clé : paramètre `api_key=`, variable `LEXIAFRIK_API_KEY`, puis le fichier enregistré par
`lexiafrik login`. Sur un serveur ou en CI, créez plutôt une clé sur le site et utilisez la variable d'environnement.

## Python

```python
from lexiafrik import LexiAfrikClient

client = LexiAfrikClient()

result = client.transcribe("discours.wav", language="wo", include_segments=True)
print(result.text)
open("discours.srt", "w", encoding="utf-8").write(result.to_srt())   # aussi to_vtt(), to_text(), to_json()

result = client.transcribe_large("conference.mp4", language="wo")     # gros fichier ou vidéo
result = client.transcribe_url("https://exemple.com/enregistrement.mp3")

for item in client.transcribe_folder("entretiens/", output_format="srt", jobs=3, recursive=True):
    print(item.status, item.path, item.error or "")
```

Segments, corrections et étiquettes (`get_segments`, `update_transcription`, `update_segment`, `get_audio_url`),
compte et usage (`get_account`, `get_usage_dashboard`), clés (`list_keys`, `create_key`, `rotate_key`,
`revoke_key`), paiements (`quote`, `create_checkout`), client asynchrone (`AsyncLexiAfrikClient`) et temps réel
(`client.realtime()`, offres Pro et Entreprise) : voir le [README anglais](README.md) et la
[documentation](https://docs.lexiafrik.com/sdk).

La gestion des équipes n'est pas disponible avec une clé d'API (elle demande une session connectée sur
lexiafrik.com) ; pour travailler sur les données d'une équipe, utilisez l'une de ses clés.

## Réessais automatiques

Les erreurs réseau, les réponses 429 (en respectant `Retry-After`) et 503 sont réessayées jusqu'à 3 fois
(`LexiAfrikClient(max_retries=0)` les désactive). Une requête qui crée quelque chose (transcription, clé, paiement)
n'est jamais répétée après un dépassement de délai ou une erreur de passerelle, car elle a pu être facturée.

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
    print(e)            # message en anglais ; e.detail contient le texte du serveur
```

Exceptions : `AuthenticationError` (401/403), `QuotaExceededError` (402), `NotFoundError` (404),
`AudioTooLargeError` (413), `UnsupportedFormatError` (415), `TranscriptionError` (422),
`RateLimitError` (429), `APIError` (5xx et réseau injoignable).

## Variables d'environnement

| Variable | Rôle |
|---|---|
| `LEXIAFRIK_API_KEY` | Clé API (prioritaire sur le fichier enregistré). |
| `LEXIAFRIK_BASE_URL` | Autre adresse d'API (tests). Défaut : `https://api.lexiafrik.com`. |
| `LEXIAFRIK_CREDENTIALS` | Autre emplacement du fichier d'identifiants. |
| `LEXIAFRIK_LANG` | Langue préférée des messages du serveur (`Accept-Language`, défaut : `en`). |

## Migration

**Depuis la 2.0 :** rien ne casse, tout le nouveau est additif. **Depuis la 1.x :** un seul type de résultat
(`TranscriptionResult`), `get_usage()` renvoie le compte (offre, quota mensuel, crédit) et non plus des limites
journalières, et les champs `model`, `n_tokens` et `rtf` n'existent plus.

## Tests

```bash
pip install httpx websockets pytest
python -m pytest tests
```

Sans réseau externe ni clé réelle.

## Obtenir une clé API

Créez un compte sur [lexiafrik.com](https://lexiafrik.com), ou lancez `lexiafrik login`.

## Licence

MIT, voir [LICENSE](LICENSE).

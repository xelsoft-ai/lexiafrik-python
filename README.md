# LexiAfrik Python SDK

SDK Python officiel pour l'[API LexiAfrik](https://api.lexiafrik.com) — transcription vocale Wolof.

## Installation

```bash
pip install lexiafrik
```

## Usage rapide

```python
from lexiafrik import LexiAfrikClient

client = LexiAfrikClient(api_key="av_votre_clé")

# Transcrire un fichier audio
result = client.transcribe("discours.wav")
print(result.text)
print(f"Durée: {result.duration_s}s | RTF: {result.rtf}")

# Transcrire depuis YouTube
result = client.transcribe_url("https://youtube.com/watch?v=abc123")
print(result.full_text)
for seg in result.segments:
    print(f"[{seg.start_s:.1f}s → {seg.end_s:.1f}s] {seg.text}")

# Vérifier l'utilisation
usage = client.get_usage()
print(f"Tier: {usage.tier} | Reste: {usage.remaining_minutes} min")
```

## Se connecter depuis le terminal

```bash
pip install lexiafrik
lexiafrik login      # affiche un code, ouvre le navigateur, enregistre une clé
lexiafrik whoami     # clé enregistrée et offre
lexiafrik logout     # supprime les identifiants et révoque la clé de ce terminal
```

`lexiafrik login` n'utilise ni mot de passe ni clé à copier : vous vous connectez sur
lexiafrik.com (email, mot de passe ou Google), vérifiez le code affiché dans le terminal
et approuvez. Une clé API dédiée à ce terminal est alors créée sur votre compte et
enregistrée dans `~/.lexiafrik/credentials.json` (lisible par vous seul). Vous pouvez la
révoquer à tout moment depuis **lexiafrik.com > Clés API**. Ensuite :

```python
client = LexiAfrikClient()   # retrouve la clé enregistrée
```

Ordre de recherche de la clé : paramètre `api_key=`, variable `LEXIAFRIK_API_KEY`, puis
fichier enregistré par `lexiafrik login`. Sur un serveur ou en CI, préférez une clé créée
sur le site et la variable d'environnement.

## Clé API via variable d'environnement

```bash
export LEXIAFRIK_API_KEY=av_votre_clé
```

```python
client = LexiAfrikClient()  # Lit LEXIAFRIK_API_KEY automatiquement
```

## Gestion des erreurs

```python
from lexiafrik import LexiAfrikClient, RateLimitError, AuthenticationError

try:
    result = client.transcribe("audio.wav")
except AuthenticationError:
    print("Clé API invalide")
except RateLimitError:
    print("Limite journalière atteinte")
```

## Context manager

```python
with LexiAfrikClient(api_key="av_...") as client:
    result = client.transcribe("audio.wav")
```

## Obtenir une clé API

Rendez-vous sur [lexiafrik.com](https://lexiafrik.com) pour créer un compte.

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

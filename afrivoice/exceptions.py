"""AfriVoice SDK — Exceptions."""


class AfriVoiceError(Exception):
    """Erreur de base du SDK AfriVoice."""
    pass


class AuthenticationError(AfriVoiceError):
    """Clé API invalide ou expirée (HTTP 401)."""
    pass


class RateLimitError(AfriVoiceError):
    """Limite de requêtes ou d'audio atteinte (HTTP 429)."""
    pass


class AudioTooLargeError(AfriVoiceError):
    """Fichier ou audio trop volumineux (HTTP 413)."""
    pass


class UnsupportedFormatError(AfriVoiceError):
    """Format audio non supporté (HTTP 415)."""
    pass


class TranscriptionError(AfriVoiceError):
    """Erreur pendant la transcription (HTTP 422)."""
    pass


class APIError(AfriVoiceError):
    """Erreur générique de l'API (HTTP 5xx)."""
    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        self.status_code = status_code

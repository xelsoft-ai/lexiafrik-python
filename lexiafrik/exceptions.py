"""LexiAfrik SDK — Exceptions."""


class LexiAfrikError(Exception):
    """Erreur de base du SDK LexiAfrik."""
    pass


class AuthenticationError(LexiAfrikError):
    """Clé API invalide ou expirée (HTTP 401)."""
    pass


class RateLimitError(LexiAfrikError):
    """Limite de requêtes ou d'audio atteinte (HTTP 429)."""
    pass


class AudioTooLargeError(LexiAfrikError):
    """Fichier ou audio trop volumineux (HTTP 413)."""
    pass


class UnsupportedFormatError(LexiAfrikError):
    """Format audio non supporté (HTTP 415)."""
    pass


class TranscriptionError(LexiAfrikError):
    """Erreur pendant la transcription (HTTP 422)."""
    pass


class APIError(LexiAfrikError):
    """Erreur générique de l'API (HTTP 5xx)."""
    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        self.status_code = status_code

"""LexiAfrik SDK — Exceptions."""


class LexiAfrikError(Exception):
    """Erreur de base du SDK LexiAfrik."""
    pass


class AuthenticationError(LexiAfrikError):
    """Clé API invalide, révoquée ou compte suspendu (HTTP 401 / 403)."""
    pass


class QuotaExceededError(LexiAfrikError):
    """Quota mensuel et crédit insuffisants (HTTP 402) : rechargez ou changez d'offre."""
    pass


class RateLimitError(LexiAfrikError):
    """Trop de requêtes ou de tentatives (HTTP 429)."""
    pass


class NotFoundError(LexiAfrikError):
    """Transcription, tâche ou clé introuvable (HTTP 404)."""
    pass


class AudioTooLargeError(LexiAfrikError):
    """Fichier trop volumineux pour cette route (HTTP 413) : utilisez transcribe_large()."""
    pass


class UnsupportedFormatError(LexiAfrikError):
    """Format audio non supporté (HTTP 415)."""
    pass


class TranscriptionError(LexiAfrikError):
    """Erreur pendant la transcription : langue inconnue, audio illisible, job en échec (HTTP 422)."""
    pass


class APIError(LexiAfrikError):
    """Erreur générique de l'API (HTTP 5xx ou inattendue)."""
    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        self.status_code = status_code

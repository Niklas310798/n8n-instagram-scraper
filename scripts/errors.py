"""Error classification: turn any failure into a user-friendly message.

Adapters raise IngestError for known cases; everything else is matched by
message and mapped to a friendly German message for the Telegram reply.
"""


class IngestError(Exception):
    def __init__(self, code: str, user_message: str, detail: str = None):
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message
        self.detail = detail or user_message


def classify(exc: Exception):
    """Return (code, user_message, detail) for any exception."""
    if isinstance(exc, IngestError):
        return exc.code, exc.user_message, exc.detail

    msg = str(exc)
    low = msg.lower()

    if "no source adapter" in low:
        return ("unsupported_url",
                "❓ Diese URL wird nicht unterstützt – aktuell nur Instagram und YouTube.",
                msg)
    if "apify" in low and "token" in low:
        return ("apify_not_configured",
                "🔧 Bild-Post erkannt, aber Apify ist nicht konfiguriert.",
                msg)
    if any(k in low for k in ("login", "empty media", "private", "not available", "be accessible")):
        return ("login_required",
                "🔒 Dieser Beitrag ist nur mit Login zugänglich und konnte nicht geladen werden.",
                msg)
    if any(k in low for k in ("rate limit", "rate-limit", "429", "too many requests")):
        return ("rate_limited",
                "🐢 Instagram/Apify bremst gerade (Rate-Limit). Bitte in ein paar Minuten erneut senden.",
                msg)
    if any(k in low for k in ("timed out", "timeout", "connection", "network", "downloaded", "expected")):
        return ("transient",
                "🔁 Temporäres Netzwerk-/Download-Problem. Bitte den Link erneut senden.",
                msg)
    if "no media" in low or "no data" in low or "not found" in low:
        return ("not_found",
                "🚫 Für diesen Link konnten keine Inhalte gefunden werden (gelöscht oder privat?).",
                msg)
    return ("internal_error",
            "⚠️ Beim Extrahieren ist ein unerwarteter Fehler aufgetreten. Bitte später erneut versuchen.",
            msg)

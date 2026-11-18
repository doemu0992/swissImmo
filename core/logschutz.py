"""Zugangslinks gehören nicht ins Protokoll.

Die Links für Handwerker (`/auftrag/<token>/`), der Direktkanal (`/direkt/<signiert>/`), der QR-Aushang
(`/aushang/<token>/`), der Fristenkalender (`?token=…`) und das Zurücksetzen des Passworts tragen ihr Geheimnis in
der Adresse. Die Datenbank hält davon höchstens einen Hash — das Protokoll hielt den Klartext: in «Internal Server
Error: /auftrag/<token>/», in den CSP-Meldungen (`document-uri`) und damit auch im Betreiber-Protokoll und dessen
CSV-Export. Wer das Protokoll lesen kann, hätte die Links benutzen können.

`GeheimnisFilter` hängt an den Handlern (`settings.LOGGING`) und kürzt beim SCHREIBEN. `bereinigen` kürzt denselben
Text beim LESEN älterer Zeilen (`core/services/betreiber_protokoll.py`).
"""
import logging
import re
import time
from pathlib import Path

#: Pfade, deren nächster Abschnitt ein Geheimnis ist.
_PFAD = re.compile(r'(/(?:auftrag|direkt|aushang)/)[^/\s?#"\'|<>]+', re.IGNORECASE)
#: Passwort zurücksetzen: /passwort/neu/<uidb64>/<token>/
_RESET = re.compile(r'(/passwort/neu/)[^/\s?#"\'|<>]+/[^/\s?#"\'|<>]+', re.IGNORECASE)
#: Abfrageteile, deren Wert ein Geheimnis ist.
_ABFRAGE = re.compile(r'([?&](?:token|signatur|sig|key|code|schluessel)=)[^&\s#"\'|<>]+', re.IGNORECASE)

ERSATZ = '…'


def bereinigen(text):
    """`text` ohne die Geheimnisse in Adressen. Verändert sonst nichts."""
    if not text or ('/' not in text and '=' not in text):
        return text
    text = _PFAD.sub(r'\1' + ERSATZ, text)
    text = _RESET.sub(r'\1' + ERSATZ, text)
    return _ABFRAGE.sub(r'\1' + ERSATZ, text)


class GeheimnisFilter(logging.Filter):
    """Kürzt Geheimnisse in der fertigen Meldung und im Traceback, bevor ein Handler sie schreibt."""

    def filter(self, record):
        try:
            meldung = record.getMessage()
            sauber = bereinigen(meldung)
            if sauber != meldung:
                record.msg, record.args = sauber, ()
            if record.exc_info and not record.exc_text:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            if record.exc_text:
                record.exc_text = bereinigen(record.exc_text)
        except Exception:                                    # noqa: BLE001 — ein Filter darf das Protokoll nie anhalten
            pass
        return True


def alte_logdateien_loeschen(tage, haupt=None, jetzt=None):
    """Löscht rotierte Logdateien (`…log.1` …), die seit `tage` Tagen nicht mehr beschrieben wurden.

    Die Rotation nach Grösse kennt kein Alter: Auf einer ruhigen Installation lagen Zeilen mit Namen und
    Mailadressen beliebig lange. Die laufende Datei bleibt (sie wird beschrieben); gibt die Zahl gelöschter zurück."""
    if haupt is None:
        from django.conf import settings
        try:
            haupt = settings.LOGGING['handlers']['file']['filename']
        except (KeyError, TypeError):
            return 0
    haupt = Path(haupt)
    grenze = (jetzt if jetzt is not None else time.time()) - tage * 86400
    geloescht = 0
    for datei in haupt.parent.glob(haupt.name + '.*'):
        try:
            if datei.is_file() and datei.stat().st_mtime < grenze:
                datei.unlink()
                geloescht += 1
        except OSError:
            continue
    return geloescht

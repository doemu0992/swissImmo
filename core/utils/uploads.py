"""Validierung von hochgeladenen Bilddateien (Foto-Uploads).

Schützt vor: zu grossen Dateien (DoS/Speicher), verkleideten Nicht-Bildern
(z.B. .php/.svg mit falscher Endung) und kaputten Dateien. Prüft echten
Bildinhalt via Pillow, nicht nur die vom Client gesendete Endung/Content-Type.
"""
import logging
from PIL import Image

logger = logging.getLogger(__name__)


# Max. 15 MB pro Bild — grosszügig für Handyfotos, aber begrenzt.
MAX_BILD_BYTES = 15 * 1024 * 1024

# Erlaubte, tatsächlich per Pillow verifizierte Bildformate.
ERLAUBTE_FORMATE = {'JPEG', 'PNG', 'GIF', 'WEBP', 'BMP', 'HEIC', 'HEIF'}


def validiere_bild(f):
    """Prüft ein hochgeladenes File-Objekt. Gibt (ok: bool, fehler: str) zurück.

    Bei Erfolg steht der Datei-Zeiger wieder am Anfang, sodass die Datei
    anschliessend normal gespeichert werden kann.
    """
    if f is None:
        return False, "Keine Datei."
    groesse = getattr(f, 'size', None)
    if groesse is not None and groesse > MAX_BILD_BYTES:
        mb = MAX_BILD_BYTES // (1024 * 1024)
        return False, f"Datei zu gross (max. {mb} MB)."
    try:
        f.seek(0)
        with Image.open(f) as img:
            img.verify()   # prüft, dass es ein echtes, unversehrtes Bild ist
            fmt = img.format
    except Exception:
        return False, "Ungültige oder beschädigte Bilddatei."
    finally:
        try:
            f.seek(0)
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)
    if fmt and fmt.upper() not in ERLAUBTE_FORMATE:
        return False, f"Bildformat {fmt} nicht erlaubt."
    return True, ""


# ---------------------------------------------------------------------------
# Dokumente (Bewerbungsunterlagen: Ausweis, Lohnausweis, Betreibungsauszug)
# ---------------------------------------------------------------------------

#: Max. 10 MB je Dokument.
MAX_DOKUMENT_BYTES = 10 * 1024 * 1024

#: Erlaubt sind PDF und Bilder — geprüft am INHALT (Magic Bytes), nicht an der
#: vom Client behaupteten Endung oder dem Content-Type.
_DOKUMENT_ENDUNGEN = {'.pdf', '.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif'}


def validiere_dokument(f):
    """Prüft ein anonym hochgeladenes Dokument (PDF oder Bild).

    Gibt `(ok, fehler)` zurück. Bei Erfolg steht der Zeiger wieder am Anfang.
    """
    import os
    if f is None:
        return False, "Keine Datei."
    if getattr(f, 'size', 0) > MAX_DOKUMENT_BYTES:
        return False, f"Datei zu gross (max. {MAX_DOKUMENT_BYTES // (1024 * 1024)} MB)."
    endung = os.path.splitext(getattr(f, 'name', '') or '')[1].lower()
    if endung not in _DOKUMENT_ENDUNGEN:
        return False, "Nur PDF- oder Bilddateien sind erlaubt."
    try:
        f.seek(0)
        kopf = f.read(16)
    finally:
        try:
            f.seek(0)
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)
    if endung == '.pdf':
        if not kopf.startswith(b'%PDF-'):
            return False, "Die Datei ist kein gültiges PDF."
        return True, ""
    return validiere_bild(f)

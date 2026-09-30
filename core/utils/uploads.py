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


# ---------------------------------------------------------------------------
# Ablage (Dokumente der Verwaltung: Pläne, Verträge, Office-Dateien)
# ---------------------------------------------------------------------------

#: Max. 25 MB je Ablagedatei (Pläne und Scans dürfen grösser sein als Belege).
MAX_ABLAGE_BYTES = 25 * 1024 * 1024

#: Bewusste Positivliste. Nicht enthalten: html/htm/svg/js (Skripte im
#: Browser des nächsten Benutzers), exe/bat/sh/php (Ausführbares).
_ABLAGE_ENDUNGEN = {'.pdf', '.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif', '.gif',
                    '.doc', '.docx', '.xls', '.xlsx', '.odt', '.ods', '.txt', '.csv',
                    '.zip', '.dwg', '.dxf'}


def validiere_ablage(f):
    """Prüft eine Datei für die interne Dokumentablage. `(ok, fehler)`.

    PDF und Bilder werden am Inhalt geprüft (`validiere_dokument`); übrige
    erlaubte Formate nur an Endung und Grösse.
    """
    import os
    if f is None:
        return False, "Keine Datei."
    name = getattr(f, 'name', '') or ''
    if '/' in name or '\\' in name or '..' in name or '\x00' in name:
        return False, "Ungültiger Dateiname."
    if getattr(f, 'size', 0) > MAX_ABLAGE_BYTES:
        return False, f"Datei zu gross (max. {MAX_ABLAGE_BYTES // (1024 * 1024)} MB)."
    endung = os.path.splitext(name)[1].lower()
    if endung not in _ABLAGE_ENDUNGEN:
        return False, "Dateityp nicht erlaubt."
    if endung in _DOKUMENT_ENDUNGEN:
        # Nicht validiere_dokument: dessen 10-MB-Grenze ist für Bewerbungsunterlagen,
        # die Ablage darf mehr (Pläne, Scans). Hier nur der Inhalt.
        try:
            f.seek(0)
            kopf = f.read(16)
        finally:
            try:
                f.seek(0)
            except Exception:
                logger.debug("Fehler bewusst übergangen", exc_info=True)
        if endung == '.pdf':
            return (True, "") if kopf.startswith(b'%PDF-') else (False, "Die Datei ist kein gültiges PDF.")
        return validiere_bild(f)   # Bilder: eigene Grenze (15 MB) und Pillow-Prüfung
    return True, ""

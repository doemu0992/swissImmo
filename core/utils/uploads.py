"""Validierung von hochgeladenen Bilddateien (Foto-Uploads).

Schützt vor: zu grossen Dateien (DoS/Speicher), verkleideten Nicht-Bildern
(z.B. .php/.svg mit falscher Endung) und kaputten Dateien. Prüft echten
Bildinhalt via Pillow, nicht nur die vom Client gesendete Endung/Content-Type.
"""
from PIL import Image

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
            pass
    if fmt and fmt.upper() not in ERLAUBTE_FORMATE:
        return False, f"Bildformat {fmt} nicht erlaubt."
    return True, ""

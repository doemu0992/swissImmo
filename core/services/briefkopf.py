"""Der Briefkopf einer Verwaltung für die HTML-Dokumente (Modul 5).

Eine Stelle für Logo, Farbe, Fusszeile und Unterschrift — gelesen aus der
Organisation DES DATENSATZES, nie aus einem Singleton (Skill
`mandantentrennung`, Regel 4). `core/templates/core/dok_base.html` liest
daraus `briefkopf`.

Bilder kommen nur als geprüfter Dateipfad hinein: xhtml2pdf bräche das ganze
Dokument ab, wenn eine verwaiste Datei verlinkt wäre (Medien nicht
mitmigriert). Fehlt die Datei, fehlt eben das Logo.
"""
import os
import re

_HEX = re.compile(r'^#[0-9A-Fa-f]{6}$')


def _pfad(bild):
    if not bild:
        return ''
    try:
        pfad = bild.path
    except (ValueError, NotImplementedError, AttributeError):
        return ''
    return pfad if pfad and os.path.isfile(pfad) else ''


def _logo_masse(pfad, hoehe=40.0, max_breite=170.0):
    """Breite und Höhe des Logos in pt, im Seitenverhältnis der Datei.

    xhtml2pdf streckt ein Bild, von dem nur die Höhe angegeben ist (Breite = Pixelzahl
    der Datei): ein breites Logo kam verzerrt aus dem PDF. Ohne lesbare Datei: (0, 0),
    die Vorlage lässt die Masse dann weg."""
    if not pfad:
        return 0, 0
    try:
        from PIL import Image
        with Image.open(pfad) as bild:
            b, h = bild.size
    except Exception:  # noqa: BLE001 — beschädigte Datei: Logo ohne Masse statt kein Dokument
        return 0, 0
    if not b or not h:
        return 0, 0
    faktor = min(hoehe / h, max_breite / b)
    return round(b * faktor, 1), round(h * faktor, 1)


def briefkopf_kontext(organisation):
    """Werte des Briefkopfs. Leer, wenn keine Organisation da ist."""
    if organisation is None:
        return {}
    from core.services.unterschrift import unterschrift_pfad
    farbe = (getattr(organisation, 'briefkopf_farbe', '') or '').strip()
    logo_pfad = _pfad(getattr(organisation, 'logo', None))
    logo_breite, logo_hoehe = _logo_masse(logo_pfad)
    return {
        'firma': organisation.firma or '',
        'strasse': organisation.strasse or '',
        'plz_ort': f"{organisation.plz or ''} {organisation.ort or ''}".strip(),
        'telefon': organisation.telefon or '',
        'email': organisation.email or '',
        'logo_pfad': logo_pfad,
        'logo_breite': logo_breite,
        'logo_hoehe': logo_hoehe,
        'unterschrift_pfad': unterschrift_pfad(organisation) or '',
        # Nochmals geprüft, obwohl das Modell validiert: Über den Admin oder
        # einen Import kann ein Wert ohne `full_clean` hineinkommen, und er
        # landet hier in einem Stilblock.
        'farbe': farbe if _HEX.match(farbe) else '',
        'fusszeile': (getattr(organisation, 'briefkopf_fusszeile', '') or '').strip(),
    }


def pfade(briefkopf):
    """Die Dateien, die ein Dokument mit diesem Briefkopf laden darf."""
    return {p for p in (briefkopf.get('logo_pfad'), briefkopf.get('unterschrift_pfad')) if p}

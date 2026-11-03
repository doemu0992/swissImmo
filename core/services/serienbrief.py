"""Serienbrief: erzeugt ein Sammel-PDF mit einem Brief pro Empfänger
(Fenstercouvert-Adressblock, Platzhalter-Ersetzung, ein Brief je Seite)."""
import logging
import io
import datetime

from reportlab.lib.units import mm

from core.services.dok_layout import LINKS, DokCanvas
from core.services.dokumentsprache import nur_deutsch

logger = logging.getLogger(__name__)


def _wrap(text, breite):
    zeilen = []
    for absatz in (text or '').split('\n'):
        worte = absatz.split(' ')
        akt = ''
        for w in worte:
            if len(akt) + len(w) + 1 > breite:
                zeilen.append(akt); akt = w
            else:
                akt = (akt + ' ' + w).strip()
        zeilen.append(akt)
    return zeilen


def _ersetze(text, e):
    ort = f"{e.get('plz','')} {e.get('ort','')}".strip()
    ersatz = {
        'name': e.get('name', ''),
        'anrede': e.get('anrede', ''),
        'strasse': e.get('strasse', ''),
        'plz': e.get('plz', ''),
        'ort': e.get('ort', ''),
        'adresse': f"{e.get('strasse','')}, {ort}".strip(', '),
        'objekt': e.get('objekt', ''),
        'liegenschaft': e.get('liegenschaft', ''),
    }
    # Der zentrale Dienst ersetzt (Modul 5): dieselben alten Namen, dazu die
    # neuen, die auf sie zeigen (`{mieter.name}` = `{name}`).
    from core.services.platzhalter import ersetze
    return ersetze(text or '', {k: (v or '') for k, v in ersatz.items()})


@nur_deutsch
def generate_serienbrief_pdf(absender, betreff, text, empfaenger, logo_path=None,
                             signatur=()):
    """absender: dict firma/strasse/plz/ort. empfaenger: Liste dicts.

    `signatur`: Objekte (Verwaltung/Eigentuemer) in Unterzeichner-Reihenfolge — der
    Brief bekommt damit die digitale Unterschrift über den Absendernamen."""
    buf = io.BytesIO()
    c = DokCanvas(buf, absender=[absender.get('firma', ''), absender.get('strasse', ''),
                                 f"{absender.get('plz', '')} {absender.get('ort', '')}".strip()],
                  logo=logo_path, titel=(betreff or '')[:70])
    heute = datetime.date.today().strftime('%d.%m.%Y')
    ort_abs = absender.get('ort', '')

    for nr, e in enumerate(empfaenger):
        if nr:
            c.neues_dokument()
        # Fenster (Adressfeld rechts), Ort/Datum und Betreff: gemeinsames Briefgerüst
        yy = c.brief([e.get('name', ''), e.get('strasse', ''), f"{e.get('plz','')} {e.get('ort','')}".strip()],
                     f"{ort_abs}, {heute}", _ersetze(betreff, e))
        # Body
        c.setFont("Helvetica", 10.5)
        for zeile in _wrap(_ersetze(text, e), 92):
            if yy < 40 * mm:
                break
            c.drawString(LINKS, yy, zeile)
            yy -= 5.6 * mm
        # Grussformel + digitale Unterschrift darüber
        yy -= 6 * mm
        c.drawString(LINKS, yy, "Freundliche Grüsse")
        yy -= 12 * mm
        if signatur:
            from core.services.unterschrift import unterschrift_zeichnen
            unterschrift_zeichnen(c, LINKS, yy + 1 * mm, *signatur)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(LINKS, yy, absender.get('firma', ''))
        c.showPage()

    c.save(); buf.seek(0)
    return buf.read()

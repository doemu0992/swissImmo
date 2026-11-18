"""Mietbestätigung (PDF) für Mieterinnen und Mieter: nur Angaben, die im Mietverhältnis stehen.

Die Verwaltung bestätigt die Anfrage (`core/services/anfragen.py`); das PDF entsteht erst beim Herunterladen, trägt aber das
Datum der Bestätigung. Es nennt Objekt, Mietbeginn, Mietzins und, ob das Mietverhältnis gekündigt ist."""
import io

from reportlab.lib.units import mm

from core.services.dok_layout import LINKS, DokCanvas
from core.services.dokumentsprache import nur_deutsch
from core.services.kuendigung_brief import _wrap

#: So lange nach der Bestätigung lässt sich das PDF laden.
GUELTIG_TAGE = 30


def _chf(wert):
    return f"CHF {float(wert):,.2f}".replace(',', "'")


def _kuendigung_text(vertrag):
    from rentals.models import Kuendigung
    k = (Kuendigung.objects.filter(vertrag=vertrag).exclude(status='zurueckgezogen')
         .order_by('-eingang_datum', '-pk').first())
    if k is None:
        return 'Das Mietverhältnis ist ungekündigt.'
    per = k.per_datum or k.berechneter_termin
    return (f"Das Mietverhältnis ist per {per:%d.%m.%Y} gekündigt." if per else 'Das Mietverhältnis ist gekündigt.')


def absaetze(mieter):
    """Pro aktivem Mietverhältnis ein Absatz (Zeilen), nur aus den Daten des Mietvertrags."""
    from core.views.portal import _mieter_objekte
    _vertraege, objekte = _mieter_objekte(mieter)
    blöcke = []
    for o in objekte:
        v = o['vertrag']
        zeilen = [f"Objekt: {o['einheit'].bezeichnung if o['einheit'] else '—'}", f"Adresse: {o['adresse']}",
                  f"Mietbeginn: {v.beginn:%d.%m.%Y}"]
        if getattr(v, 'ist_befristet', False) and v.ende:
            zeilen.append(f"Befristet bis: {v.ende:%d.%m.%Y}")
        zeilen += [f"Nettomietzins pro Monat: {_chf(o['netto'] or 0)}", f"Nebenkosten pro Monat: {_chf(o['nk'] or 0)}",
                   f"Bruttomietzins pro Monat: {_chf(o['brutto'])}", _kuendigung_text(v)]
        blöcke.append(zeilen)
    return blöcke


@nur_deutsch
def mietbestaetigung_pdf(mieter, ausgestellt_am, verwaltung=None):
    """PDF-Bytes. Gibt es kein aktives Mietverhältnis, steht das ehrlich im Text (kein erfundener Inhalt)."""
    verwaltung = verwaltung or mieter.organisation
    buf = io.BytesIO()
    v_name = getattr(verwaltung, 'firma', '') or 'Liegenschaftsverwaltung'
    v_str = getattr(verwaltung, 'strasse', '') or ''
    v_ort = f"{getattr(verwaltung, 'plz', '') or ''} {getattr(verwaltung, 'ort', '') or ''}".strip()
    m_ort = f"{mieter.plz or ''} {mieter.ort or ''}".strip()
    c = DokCanvas(buf, absender=[v_name, v_str, v_ort], titel='Mietbestätigung', ref=mieter.display_name)
    yy = c.brief([mieter.display_name, mieter.strasse or '', m_ort], f"{ausgestellt_am:%d.%m.%Y}", 'Mietbestätigung')
    c.setFont('Helvetica', 10.5)
    kopf = (f"Wir bestätigen auf Ihre Anfrage, dass {mieter.display_name} bei uns ein Mietverhältnis hat:"
            if absaetze(mieter) else
            f"Auf Ihre Anfrage teilen wir mit, dass für {mieter.display_name} derzeit kein aktives Mietverhältnis "
            "bei uns geführt wird.")
    zeilen = _wrap(kopf, 90) + ['']
    for i, block in enumerate(absaetze(mieter)):
        if i:
            zeilen.append('')
        zeilen += block
    zeilen += ['', f"Ausgestellt am {ausgestellt_am:%d.%m.%Y} auf Anfrage der Mieterschaft.", '', 'Freundliche Grüsse', v_name]
    for z in zeilen:
        if yy < 40 * mm:
            break
        c.drawString(LINKS, yy, z)
        yy -= 5.8 * mm
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()

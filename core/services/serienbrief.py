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
    # `_ph` (23.11.2026): der volle Kontext des Empfängers aus `empfaenger_kontext` — damit lösen sich auch
    # `{mieter.anrede}`, `{objekt.adresse}`, `{verwaltung.telefon}` oder `{frist}` auf, die Vorlagen heute verwenden.
    # Die alten flachen Namen behalten Vorrang und damit ihre bisherige Bedeutung.
    from core.services.platzhalter import ersetze
    kontext = dict(e.get('_ph') or {})
    kontext.update({k: (v or '') for k, v in ersatz.items()})
    return ersetze(text or '', kontext)


def empfaenger_kontext(mieter, organisation=None, frist_datum=None, frist_tage=None, vertrag=None):
    """Alle Platzhalterwerte für EINEN Empfänger des Rundschreibens: `(vertrag, kontext)`.

    Dieselbe Quelle für Live-Vorschau, Serienbrief-PDF und E-Mail (`core.services.platzhalter.kontext_fuer`). Ohne
    `vertrag` gilt der aktive Vertrag der Person (als Mieter oder Mitmieter); hat sie keinen, kommen nur die Werte
    der Person und der Verwaltung."""
    from django.db.models import Q

    from core.services.platzhalter import kontext_fuer
    from rentals.models import Mietvertrag
    if vertrag is None:
        vertrag = (Mietvertrag.objects.filter(Q(mieter=mieter) | Q(mitmieter=mieter), status='aktiv')
                   .select_related('einheit__liegenschaft', 'mieter', 'mitmieter').first())
    return vertrag, kontext_fuer(vertrag=vertrag, mieter=mieter, organisation=organisation,
                                 frist_datum=frist_datum, frist_tage=frist_tage)


def frist_aus(werte):
    """`(frist_datum, frist_tage)` aus Formular- oder Auftragswerten; Ungültiges wird zu None."""
    from core.services.brief_aus_vorlage import FRIST_MAX_TAGE
    datum = None
    roh = str(werte.get('frist_datum') or '').strip()
    if roh:
        try:
            datum = datetime.date.fromisoformat(roh)
        except ValueError:
            datum = None
    try:
        tage = int(werte.get('frist_tage') or 0)
    except (TypeError, ValueError):
        tage = 0
    return datum, (tage if 0 < tage <= FRIST_MAX_TAGE else None)


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

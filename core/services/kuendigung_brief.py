"""Mieter-Kündigungsbrief (ordentliche Kündigung durch den Mieter).

Erzeugt einen druckfertigen Brief zum Versand per Einschreiben. Bei einer
Familienwohnung werden zwei Unterschriftszeilen gesetzt (Art. 266m OR —
beide Ehegatten müssen kündigen)."""
import io
import datetime

from reportlab.lib.units import mm

from core.services.dok_layout import LINKS, DokCanvas
from core.services.dokumentsprache import nur_deutsch


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


@nur_deutsch
def generate_kuendigung_mieter_pdf(vertrag, kuendigung, verwaltung=None, eigentuemer=None):
    """vertrag: Mietvertrag, kuendigung: Kuendigung (per_datum/berechneter_termin)."""
    buf = io.BytesIO()
    mieter = vertrag.mieter
    einheit = vertrag.einheit
    lg = einheit.liegenschaft if einheit else None

    # Empfänger: Eigentümer bevorzugt, sonst Verwaltung
    if eigentuemer is not None:
        e_name = eigentuemer.firma_oder_name
        e_str = eigentuemer.strasse or ''
        e_ort = f"{eigentuemer.plz or ''} {eigentuemer.ort or ''}".strip()
    elif verwaltung is not None:
        e_name = verwaltung.firma
        e_str = verwaltung.strasse or ''
        e_ort = f"{verwaltung.plz or ''} {verwaltung.ort or ''}".strip()
    else:
        e_name, e_str, e_ort = 'Liegenschaftsverwaltung', '', ''

    # Absender (Mieter)
    a_name = mieter.display_name
    a_str = mieter.strasse or (lg.strasse if lg else '')
    a_ort = f"{mieter.plz or ''} {mieter.ort or ''}".strip() or (f"{lg.plz} {lg.ort}" if lg else '')

    per = kuendigung.per_datum or kuendigung.berechneter_termin
    per_str = per.strftime('%d.%m.%Y') if per else 'nächstmöglichen Termin'
    heute = datetime.date.today().strftime('%d.%m.%Y')

    # Absender ist der Mieter (er kündigt): sein Name und seine Adresse stehen im Briefkopf,
    # nicht die der Verwaltung. Empfänger im Fenster rechts, Einschreiben-Vermerk links davon.
    c = DokCanvas(buf, absender=[a_name, a_str, a_ort], titel='Kündigung des Mietvertrags', ref=a_name)
    ort_abs = (mieter.ort or (lg.ort if lg else '')) or ''
    objekt = einheit.bezeichnung if einheit else ''
    objekt_adr = f"{lg.strasse}, {lg.plz} {lg.ort}" if lg else ''
    yy = c.brief([e_name, e_str, e_ort], f"{ort_abs}, {heute}".strip(', '),
                 f"Kündigung des Mietvertrags per {per_str}", einschreiben=True)

    # Text
    familienwohnung = bool(getattr(vertrag, 'familienwohnung', False)) or bool(getattr(vertrag, 'mitmieter_name', ''))
    anrede = "Sehr geehrte Damen und Herren"
    body = (
        f"{anrede}\n\n"
        f"Hiermit kündige{'n wir' if familienwohnung else ' ich'} den Mietvertrag für das nachstehende "
        f"Mietobjekt ordentlich und fristgerecht per {per_str}:\n\n"
        f"Objekt: {objekt}\n"
        f"Adresse: {objekt_adr}\n"
        f"Mietbeginn: {vertrag.beginn.strftime('%d.%m.%Y') if vertrag.beginn else '—'}\n\n"
        f"{'Wir bitten' if familienwohnung else 'Ich bitte'} Sie um eine schriftliche Bestätigung "
        f"dieser Kündigung sowie des Auszugstermins. Gerne vereinbaren "
        f"{'wir' if familienwohnung else 'ich'} mit Ihnen einen Termin für die Wohnungsabnahme."
    )
    if getattr(kuendigung, 'bemerkung', ''):
        body += f"\n\nBemerkung: {kuendigung.bemerkung}"

    c.setFont("Helvetica", 10.5)
    for zeile in _wrap(body, 90):
        if yy < 80 * mm:
            break
        c.drawString(LINKS, yy, zeile)
        yy -= 5.8 * mm

    # Grussformel
    yy -= 6 * mm
    c.setFont("Helvetica", 10.5)
    c.drawString(LINKS, yy, "Freundliche Grüsse")

    # Unterschriftszeilen (bei Familienwohnung zwei)
    yy -= 24 * mm
    c.setStrokeColorRGB(0.3, 0.3, 0.3)
    c.line(LINKS, yy, 85 * mm, yy)
    c.setFont("Helvetica", 9)
    c.drawString(LINKS, yy - 5 * mm, a_name)
    if familienwohnung:
        c.line(110 * mm, yy, 175 * mm, yy)
        zweit = getattr(vertrag, 'mitmieter_name', '') or 'Mitmieter/in'
        c.drawString(110 * mm, yy - 5 * mm, zweit)
        c.setFont("Helvetica-Oblique", 8)
        c.setFillColorRGB(0.45, 0.45, 0.45)
        c.drawString(LINKS, yy - 12 * mm,
                     "Familienwohnung: Die Kündigung ist nur mit der Unterschrift beider Ehegatten/Partner gültig (Art. 266m OR).")
        c.setFillColorRGB(0, 0, 0)

    # Fusszeile Hinweis
    c.setFont("Helvetica-Oblique", 7.5)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawString(LINKS, 30 * mm,
                 "Bitte per Einschreiben versenden. Massgebend für die Fristwahrung ist der Zugang beim Vermieter, nicht der Poststempel.")
    c.setFillColorRGB(0, 0, 0)

    c.showPage(); c.save(); buf.seek(0)
    return buf.read()

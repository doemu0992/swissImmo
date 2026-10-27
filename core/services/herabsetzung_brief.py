"""Antwortbrief der Verwaltung auf ein Herabsetzungsbegehren (Art. 270a OR).

Bis 26.10.2026 hielt `fw_herabsetzung` nur das Ergebnis der Antwort fest — der
Brief selbst entstand ausserhalb der Anwendung, und in der Akte stand nicht, was
dem Mieter geantwortet worden war. Die Frist des Mieters zur Anrufung der
Schlichtungsbehörde (30 Tage, Art. 270a Abs. 3 OR — derselbe Wert wie in der
Pendenz der View) läuft aber ab dieser Antwort; ihr Inhalt gehört in die Akte.

Briefkopf und Absender kommen aus der Organisation des Vertrags (Skill
`mandantentrennung`, Regel 4), nie aus einem Singleton. Rechtstext: deutsch bis
zur juristisch geprüften Übersetzung (Entscheid D11).
"""
import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from core.services.dokumentsprache import nur_deutsch

#: Art. 270a Abs. 3 OR: Anrufung der Schlichtungsbehörde innert 30 Tagen.
ANRUFUNG_TAGE = 30

ERGEBNIS_TEXT = {
    'zustimmung': 'Zustimmung',
    'teilweise': 'Teilweise Zustimmung',
    'ablehnung': 'Ablehnung',
}


def _zeilen(text, breite=95):
    aus = []
    for absatz in (text or '').split('\n'):
        akt = ''
        for wort in absatz.split(' '):
            if len(akt) + len(wort) + 1 > breite:
                aus.append(akt)
                akt = wort
            else:
                akt = (akt + ' ' + wort).strip()
        aus.append(akt)
    return aus


def _chf(betrag):
    return f"{betrag:,.2f}".replace(',', "'")


@nur_deutsch
def antwortbrief_pdf(vertrag, ergebnis, antwort_am, eingang_am=None, begruendung='',
                     neu_netto=None, wirksam_ab=None):
    """PDF des Antwortbriefs. `ergebnis` ∈ ERGEBNIS_TEXT."""
    if ergebnis not in ERGEBNIS_TEXT:
        raise ValueError(f'Unbekanntes Ergebnis: {ergebnis}')
    org = vertrag.organisation
    mieter = vertrag.mieter
    einheit = vertrag.einheit
    lg = einheit.liegenschaft if einheit else None

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle('Antwort auf das Herabsetzungsbegehren')

    # Absender (Verwaltung des Vertrags)
    c.setFont('Helvetica-Bold', 10)
    y = 280 * mm
    c.drawString(25 * mm, y, getattr(org, 'firma', '') or '')
    c.setFont('Helvetica', 10)
    for zeile in (getattr(org, 'strasse', ''), f"{getattr(org, 'plz', '') or ''} {getattr(org, 'ort', '') or ''}".strip()):
        if zeile:
            y -= 5 * mm
            c.drawString(25 * mm, y, zeile)

    # Empfänger (Mieter)
    c.setFont('Helvetica', 11)
    y = 250 * mm
    for zeile in (mieter.display_name, mieter.strasse or (lg.strasse if lg else ''),
                  f"{mieter.plz or ''} {mieter.ort or ''}".strip() or (f"{lg.plz} {lg.ort}" if lg else '')):
        if zeile:
            c.drawString(120 * mm, y, zeile)
            y -= 5 * mm

    c.setFont('Helvetica', 10)
    ort = getattr(org, 'ort', '') or ''
    c.drawString(120 * mm, 215 * mm, f"{ort + ', ' if ort else ''}{antwort_am:%d.%m.%Y}")

    c.setFont('Helvetica-Bold', 12)
    c.drawString(25 * mm, 200 * mm, 'Ihr Herabsetzungsbegehren (Art. 270a OR)')
    c.setFont('Helvetica', 10)
    objekt = f"{einheit.bezeichnung}, {lg.strasse}, {lg.plz} {lg.ort}" if (einheit and lg) else str(einheit or '')
    c.drawString(25 * mm, 194 * mm, f"Mietobjekt: {objekt}")

    eingang = f" vom {eingang_am:%d.%m.%Y}" if eingang_am else ''
    absaetze = [f"Sehr geehrte Damen und Herren\n\nWir beziehen uns auf Ihr Begehren um Herabsetzung "
                f"des Mietzinses{eingang}."]
    if ergebnis == 'zustimmung':
        satz = 'Wir entsprechen Ihrem Begehren.'
    elif ergebnis == 'teilweise':
        satz = 'Wir entsprechen Ihrem Begehren teilweise.'
    else:
        satz = 'Wir können Ihrem Begehren nicht entsprechen.'
    if ergebnis != 'ablehnung' and neu_netto is not None:
        satz += f" Der Nettomietzins beträgt neu CHF {_chf(neu_netto)}"
        satz += f" ab {wirksam_ab:%d.%m.%Y}." if wirksam_ab else '.'
        satz += (' Die Anpassung teilen wir Ihnen zusätzlich mit dem amtlichen Formular mit.')
    absaetze.append(satz)
    if (begruendung or '').strip():
        absaetze.append('Begründung: ' + begruendung.strip())
    if ergebnis != 'zustimmung':
        absaetze.append(f"Sind Sie mit dieser Antwort nicht einverstanden, können Sie innert {ANRUFUNG_TAGE} "
                        "Tagen ab Erhalt die Schlichtungsbehörde anrufen (Art. 270a Abs. 3 OR).")
    absaetze.append('Freundliche Grüsse\n\n' + (getattr(org, 'firma', '') or ''))

    y = 182 * mm
    for absatz in absaetze:
        for zeile in _zeilen(absatz):
            c.drawString(25 * mm, y, zeile)
            y -= 5 * mm
        y -= 3 * mm
    c.showPage()
    c.save()
    return buf.getvalue()

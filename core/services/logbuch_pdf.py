"""PDF-Auditbericht des Logbuchs (revisionssicher, für die Ablage/Prüfung).

Erzeugt eine schlichte, tabellarische Liste der Aktivitäts-Einträge mit
Zeitpunkt, Benutzer, Aktion, Objekt und Details."""
import io
import datetime

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm


def _wrap(text, breite):
    """Bricht Text grob auf `breite` Zeichen um."""
    text = str(text or '')
    zeilen, aktuell = [], ''
    for wort in text.split(' '):
        if len(aktuell) + len(wort) + 1 > breite:
            if aktuell:
                zeilen.append(aktuell)
            aktuell = wort
        else:
            aktuell = (aktuell + ' ' + wort).strip()
    if aktuell:
        zeilen.append(aktuell)
    return zeilen or ['']


def _kopfzeile(gezeigt, gesamt):
    """Sagt, wenn der Bericht nur ein Ausschnitt ist.

    «unveraenderlicher Revisions-Trail» darf nur dastehen, wenn der Bericht
    auch vollstaendig ist. Bei mehr Eintraegen als der Obergrenze wird daraus
    eine Ansage — sonst legt jemand einer Revision einen Ausschnitt vor und
    haelt ihn fuer das Ganze.
    """
    if gesamt is not None and gesamt > gezeigt:
        return (f"{gezeigt} von {gesamt} Eintraegen · AUSSCHNITT, nach "
                f"Zeitpunkt absteigend · fuer den vollstaendigen Trail bitte "
                f"den Zeitraum eingrenzen")
    return f"{gezeigt} Eintraege · unveraenderlicher Revisions-Trail"


def logbuch_pdf(eintraege, erstellt_von='', heute=None, gesamt=None):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    heute = heute or datetime.date.today().strftime('%d.%m.%Y')

    def kopf():
        c.setFont("Helvetica-Bold", 15)
        c.drawString(20 * mm, H - 20 * mm, "Logbuch — Auditbericht")
        c.setFont("Helvetica", 8.5); c.setFillColorRGB(0.4, 0.4, 0.4)
        c.drawString(20 * mm, H - 26 * mm,
                     f"Erstellt am {heute}{(' von ' + erstellt_von) if erstellt_von else ''} · "
                     + _kopfzeile(len(eintraege), gesamt))
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 8)
        y = H - 34 * mm
        c.drawString(20 * mm, y, "Zeitpunkt")
        c.drawString(52 * mm, y, "Benutzer")
        c.drawString(85 * mm, y, "Aktion")
        c.drawString(130 * mm, y, "Objekt / Details")
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.line(20 * mm, y - 1.5 * mm, W - 20 * mm, y - 1.5 * mm)
        return y - 6 * mm

    y = kopf()
    c.setFont("Helvetica", 7.5)
    for e in eintraege:
        wer = (e.benutzer.get_full_name() or e.benutzer.username) if e.benutzer else 'System'
        detail = e.objekt or ''
        if e.details:
            detail = (detail + ' — ' + e.details) if detail else e.details
        det_zeilen = _wrap(detail, 55)
        hoehe = max(len(det_zeilen), 1) * 3.6 * mm + 1.5 * mm

        if y - hoehe < 20 * mm:
            c.showPage()
            y = kopf()
            c.setFont("Helvetica", 7.5)

        try:
            zeit = e.zeitpunkt.strftime('%d.%m.%Y %H:%M')
        except Exception:
            zeit = ''
        c.drawString(20 * mm, y, zeit)
        c.drawString(52 * mm, y, wer[:20])
        c.drawString(85 * mm, y, (e.aktion or '')[:32])
        for i, z in enumerate(det_zeilen):
            c.drawString(130 * mm, y - i * 3.6 * mm, z)
        y -= hoehe

    # Fusszeile: Aufbewahrung
    c.setFont("Helvetica-Oblique", 7); c.setFillColorRGB(0.45, 0.45, 0.45)
    c.drawString(20 * mm, 14 * mm,
                 "Geschäftsbücher und Belege sind 10 Jahre aufzubewahren (Art. 958f OR).")
    c.setFillColorRGB(0, 0, 0)
    c.showPage()
    c.save()
    return buf.getvalue()

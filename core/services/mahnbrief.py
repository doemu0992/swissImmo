"""Das Schreiben der automatischen Mahnstufen — ehrlich beschriftet.

WARUM ES DAS GIBT (Stresstest 30.09.2026, Punkte 5–7)

Der Mahnlauf legte bei JEDER Stufe — schon der ersten nach 14 Tagen — ein PDF
«Zahlungsverzug gemäss Art. 257d OR – Kündigungsandrohung, 30 Tage» in der
Akte ab. Zugestellt wurde nur eine einfache Zahlungserinnerung per E-Mail. Die
Akte behauptete damit eine Fristansetzung, die nie stattgefunden hat, und nannte
für die Dezembermiete «Monat Februar», weil der Kalendermonat von heute
eingesetzt wurde.

Eine 257d-Fristansetzung ist ein eingeschriebener, unterschriebener Brief mit
Kündigungsandrohung (`fw_verzug_257d`). Die Mahnstufen davor sind Mahnungen,
nichts weiter. Dieses Modul erzeugt sie: mit dem Monat der Forderung, dem
offenen Betrag und — auf der letzten Stufe — dem ausdrücklichen Hinweis, dass die
formelle Fristansetzung separat folgt. «Kündigung» steht hier nie als
angedroht, weil sie hier nicht angedroht wird.
"""
import io

import logging

from core.services.dokumentsprache import nur_deutsch
from core.services.pdf_text import format_chf

logger = logging.getLogger(__name__)

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]


def monat_text(d):
    """«Dezember 2025» für ein Datum — der Monat der FORDERUNG, nicht der von heute."""
    return f"{MONATE[d.month - 1]} {d.year}"


def forderungs_monat(rechnung):
    """Monat der Forderung: Fälligkeit, sonst Rechnungsdatum."""
    d = rechnung.faellig_am or rechnung.datum
    return monat_text(d) if d else ''


_TITEL = {
    1: "Zahlungserinnerung",
    2: "2. Mahnung",
    3: "3. Mahnung – letzte Mahnung",
}


@nur_deutsch
def mahnbrief_pdf(vertrag, verwaltung, *, stufe, monat, betrag, datum,
                  gebuehr=None, letzte_stufe=False, rechnung=None):
    """Mahnschreiben der Stufe `stufe` als PDF-Bytes (Brief + QR-Rechnung).

    `letzte_stufe`: Die Stufe führt laut Konfiguration zur 257d-Fristansetzung —
    das Schreiben kündigt sie als nächsten Schritt an (ohne sie zu setzen).
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    from core.utils.qr_code import draw_qr_bill

    m = vertrag.mieter
    betrag_roh = betrag                       # für den QR-Betrag: Zahl, kein Anzeigetext
    betrag = format_chf(betrag_roh) or '0.00'  # Anzeige: CHF 1'250.50
    if hasattr(monat, 'month'):               # Datum statt fertigem «Januar 2025»
        monat = monat_text(monat)
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    links = 25 * mm
    fenster = 120 * mm

    if verwaltung:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(links, 280 * mm, verwaltung.firma)
        c.setFont("Helvetica", 9)
        c.drawString(links, 275 * mm, f"{verwaltung.strasse}, {verwaltung.plz} {verwaltung.ort}")

    y = 250 * mm
    c.setFont("Helvetica", 11)
    if getattr(m, 'firma', None):
        c.drawString(fenster, y, m.firma); y -= 5 * mm
    c.drawString(fenster, y, f"{m.vorname} {m.nachname}".strip())
    c.drawString(fenster, y - 5 * mm, m.strasse or '')
    c.drawString(fenster, y - 10 * mm, f"{m.plz} {m.ort}")

    c.setFont("Helvetica", 10)
    c.drawString(links, 210 * mm, ", ".join(t for t in ((verwaltung.ort if verwaltung else ''), f"{datum:%d.%m.%Y}") if t))
    c.setFont("Helvetica-Bold", 12)
    c.drawString(links, 195 * mm, _TITEL.get(stufe, f"{stufe}. Mahnung"))
    c.setFont("Helvetica-Bold", 10)
    e = vertrag.einheit
    c.drawString(links, 189 * mm, f"Mietobjekt: {e.bezeichnung}, {e.liegenschaft.strasse}")

    anrede = getattr(m, 'anrede', '')
    if anrede == "Herr":
        gruss = f"Sehr geehrter Herr {m.nachname},"
    elif anrede == "Frau":
        gruss = f"Sehr geehrte Frau {m.nachname},"
    else:
        gruss = "Sehr geehrte Damen und Herren,"

    zeilen = [gruss, ""]
    if stufe <= 1:
        zeilen += [f"bei der Kontrolle unserer Zahlungseingänge haben wir festgestellt, dass für",
                   f"{monat} noch CHF {betrag} ausstehend sind.", "",
                   "Sicher haben Sie die Zahlung nur übersehen. Wir bitten Sie, den Betrag",
                   "in den nächsten Tagen zu überweisen."]
    else:
        zeilen += [f"trotz unserer früheren Schreiben ist die Forderung für {monat} über",
                   f"CHF {betrag} weiterhin offen.", "",
                   "Wir bitten Sie, den Betrag umgehend zu überweisen."]
    if gebuehr and gebuehr > 0:
        zeilen += ["", f"Für diese Mahnung stellen wir eine Mahngebühr von CHF {format_chf(gebuehr)} in Rechnung."]
    if letzte_stufe:
        zeilen += ["", "Dies ist unsere letzte Mahnung. Bleibt die Zahlung weiterhin aus, setzen wir",
                   "Ihnen in einem gesonderten, eingeschriebenen Schreiben eine Zahlungsfrist nach",
                   "Art. 257d OR an. Bei fruchtlosem Ablauf dieser Frist wäre eine ausserordentliche",
                   "Kündigung möglich."]
    zeilen += ["", "Hat sich Ihre Zahlung mit diesem Schreiben gekreuzt, betrachten Sie es",
               "bitte als gegenstandslos.", "", "Freundliche Grüsse", "",
               verwaltung.firma if verwaltung else "Die Vermieterschaft"]

    ty = 175 * mm
    for zeile in zeilen:
        c.setFont("Helvetica", 11)
        c.drawString(links, ty, zeile)
        ty -= 5.5 * mm

    lg = e.liegenschaft
    iban = getattr(lg, 'iban', None) or getattr(verwaltung, 'iban', None)
    if iban:
        try:
            c.showPage()
            if verwaltung:
                creditor = {'name': verwaltung.firma, 'line1': verwaltung.strasse,
                            'line2': f"{verwaltung.plz} {verwaltung.ort}",
                            'plz': verwaltung.plz or '', 'ort': verwaltung.ort or ''}
            else:
                creditor = {'name': "Verwaltung", 'line1': lg.strasse,
                            'line2': f"{lg.plz} {lg.ort}"}
            debtor = {'name': (getattr(m, 'firma', None) or f"{m.vorname} {m.nachname}").strip(),
                      'line1': m.strasse or '', 'line2': f"{m.plz} {m.ort}"}
            draw_qr_bill(c, iban, creditor, debtor, float(str(betrag_roh).replace("'", '').replace(',', '.')),
                         f"{_TITEL.get(stufe, 'Mahnung')} {monat} {e.bezeichnung}",
                         reference=getattr(rechnung, 'qr_referenz', None) or None)
        except Exception:
            # Ohne QR-Teil ist die Mahnung nicht einzahlbar — das darf im
            # Betrieb nicht unbemerkt bleiben.
            logger.error("QR-Rechnung der Mahnung nicht erzeugt (Vertrag %s)", vertrag.pk, exc_info=True)
    c.save()
    buffer.seek(0)
    return buffer.getvalue()

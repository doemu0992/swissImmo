"""Eigentümer-/Mandatsabrechnung als PDF.

Stellt je Liegenschaft eines Eigentümers Erträge und Aufwände eines Geschäftsjahres
gegenüber und weist den Saldo (Auszahlung an den Eigentümer) aus."""
import logging
import io
from decimal import Decimal

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors
from django.utils.translation import gettext

from core.services.dokumentsprache import in_sprache, sprache_von

logger = logging.getLogger(__name__)



def _fmt(d):
    try:
        return f"{Decimal(str(d)):,.2f}".replace(",", "'")
    except Exception:
        return str(d)


def generate_mandat_abrechnung_pdf(eigentuemer, jahr, zeilen, totals, von, bis, verwaltung=None):
    """In der Korrespondenzsprache des Eigentümers (D11): eine Zahlenaufstellung
    ohne Rechtstext, deshalb übersetzt."""
    with in_sprache(sprache_von(eigentuemer)):
        return _pdf(eigentuemer, jahr, zeilen, totals, von, bis, verwaltung)


def _pdf(eigentuemer, jahr, zeilen, totals, von, bis, verwaltung):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(gettext('Mandatsabrechnung %(name)s %(jahr)s') % {'name': eigentuemer.firma_oder_name, 'jahr': jahr})

    if verwaltung and getattr(verwaltung, 'logo', None):
        try:
            c.drawImage(verwaltung.logo.path, 155*mm, 272*mm, width=40*mm, preserveAspectRatio=True, mask='auto')
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)

    # Absender
    if verwaltung:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(20*mm, 280*mm, verwaltung.firma or "")
        c.setFont("Helvetica", 9)
        c.drawString(20*mm, 276*mm, verwaltung.strasse or "")
        c.drawString(20*mm, 272*mm, f"{verwaltung.plz or ''} {verwaltung.ort or ''}".strip())

    # Empfänger (Eigentümer)
    c.setFont("Helvetica", 11)
    c.drawString(20*mm, 250*mm, eigentuemer.firma_oder_name)
    if eigentuemer.kontaktperson:
        c.drawString(20*mm, 245*mm, eigentuemer.kontaktperson)
    c.drawString(20*mm, 240*mm, eigentuemer.strasse or "")
    c.drawString(20*mm, 235*mm, f"{eigentuemer.plz or ''} {eigentuemer.ort or ''}".strip())

    # Titel
    c.setFont("Helvetica-Bold", 15)
    c.drawString(20*mm, 218*mm, gettext('Eigentümerabrechnung %(jahr)s') % {'jahr': jahr})
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.grey)
    c.drawString(20*mm, 212*mm, gettext('Abrechnungsperiode: %(von)s – %(bis)s') % {
        'von': von.strftime('%d.%m.%Y'), 'bis': bis.strftime('%d.%m.%Y')})
    c.setFillColor(colors.black)

    # Tabellenkopf
    y = 198*mm
    c.setFillColor(colors.HexColor("#EEF0F5"))
    c.rect(18*mm, y - 2*mm, 174*mm, 8*mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(22*mm, y, gettext('Liegenschaft'))
    c.drawRightString(120*mm, y, gettext('Ertrag'))
    c.drawRightString(155*mm, y, gettext('Aufwand'))
    c.drawRightString(188*mm, y, gettext('Saldo'))

    y -= 9*mm
    c.setFont("Helvetica", 9)
    for z in zeilen:
        if y < 60*mm:
            c.showPage()
            y = 270*mm
        lg = z['lg']
        c.drawString(22*mm, y, f"{lg.strasse}, {lg.ort}"[:52])
        c.drawRightString(120*mm, y, _fmt(z['ertrag']))
        c.drawRightString(155*mm, y, _fmt(z['aufwand']))
        c.setFillColor(colors.HexColor("#B91C1C") if z['saldo'] < 0 else colors.black)
        c.drawRightString(188*mm, y, _fmt(z['saldo']))
        c.setFillColor(colors.black)
        y -= 6*mm

    if not zeilen:
        c.setFillColor(colors.grey)
        c.drawString(22*mm, y, gettext('Keine Liegenschaften diesem Eigentümer zugeordnet.'))
        c.setFillColor(colors.black)
        y -= 6*mm

    # Total
    y -= 2*mm
    c.setLineWidth(0.6)
    c.line(18*mm, y, 192*mm, y)
    y -= 7*mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(22*mm, y, gettext('Total'))
    c.drawRightString(120*mm, y, _fmt(totals['ertrag']))
    c.drawRightString(155*mm, y, _fmt(totals['aufwand']))
    c.drawRightString(188*mm, y, _fmt(totals['saldo']))

    # Auszahlungsbox
    y -= 16*mm
    saldo = totals['saldo']
    c.setFillColor(colors.HexColor("#ECFDF5") if saldo >= 0 else colors.HexColor("#FEF2F2"))
    c.rect(18*mm, y - 6*mm, 174*mm, 16*mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 12)
    label = gettext('Auszahlung an Eigentümer') if saldo >= 0 else gettext('Nachschuss durch Eigentümer')
    c.drawString(22*mm, y, label)
    c.drawRightString(188*mm, y, f"CHF {_fmt(abs(saldo))}")

    # Fusszeile
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    c.drawString(20*mm, 20*mm, gettext('Diese Abrechnung basiert auf den verbuchten Erträgen und Aufwänden der zugeordneten Liegenschaften.'))
    if eigentuemer.iban:
        c.drawString(20*mm, 16*mm, gettext('Auszahlung auf: %(iban)s') % {'iban': eigentuemer.iban})
    c.setFillColor(colors.black)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()

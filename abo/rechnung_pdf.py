"""Die Abo-Rechnung als A4-PDF mit QR-Einzahlungsschein.

Nutzt den vorhandenen Zahlteil (`core.utils.qr_code.draw_qr_bill`) und die
QRR-Referenz (`qrr_referenz`), wie die Debitorenrechnung der Verwaltung
(`core/services/debitor_qr.py`). Gläubiger ist die «Plattform»
(`settings.ABO_RECHNUNGSSTELLER`), Schuldner die Organisation.

Ohne hinterlegte IBAN des Betreibers gibt es kein PDF (`None`): Ein
Einzahlungsschein ohne Konto wäre ein Dokument, das niemand bezahlen kann.
"""
import io

from django.conf import settings

from core.services.dokumentsprache import nur_deutsch


def _chf(wert):
    return f"CHF {float(wert):,.2f}".replace(",", "'")


def steller():
    return settings.ABO_RECHNUNGSSTELLER


@nur_deutsch
def abo_rechnung_pdf(rechnung):
    """PDF-Bytes der Rechnung, oder `None`, wenn der Betreiber keine IBAN festgelegt hat."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    from core.utils.qr_code import draw_qr_bill

    s = steller()
    iban = (s.get('iban') or '').replace(' ', '')
    if not iban:
        return None
    org = rechnung.organisation
    creditor = {'name': s.get('name') or 'Plattform', 'line1': s.get('strasse', ''),
                'line2': f"{s.get('plz', '')} {s.get('ort', '')}".strip(),
                'plz': s.get('plz', ''), 'ort': s.get('ort', '')}
    debtor = {'name': org.firma, 'line1': org.strasse or '',
              'line2': f"{org.plz or ''} {org.ort or ''}".strip(),
              'plz': org.plz or '', 'ort': org.ort or ''}

    puffer = io.BytesIO()
    c = canvas.Canvas(puffer, pagesize=A4)
    c.setTitle(f'Rechnung {rechnung.nummer}')
    c.setFont('Helvetica-Bold', 18)
    c.drawString(20 * mm, 270 * mm, 'Rechnung')
    c.setFont('Helvetica', 10)
    c.setFillColor(colors.darkgrey)
    c.drawString(20 * mm, 263 * mm, f'{rechnung.nummer} · Abonnement immoswiss')
    c.setFillColor(colors.black)

    y = 250 * mm
    c.setFont('Helvetica', 9)
    c.drawString(20 * mm, y, 'Rechnungsempfänger:')
    c.setFont('Helvetica-Bold', 11)
    c.drawString(20 * mm, y - 6 * mm, debtor['name'])
    c.setFont('Helvetica', 11)
    c.drawString(20 * mm, y - 11 * mm, debtor['line1'])
    c.drawString(20 * mm, y - 16 * mm, debtor['line2'])
    c.setFont('Helvetica', 10)
    c.drawRightString(190 * mm, y, f'Datum: {rechnung.rechnungsdatum:%d.%m.%Y}')
    c.drawRightString(190 * mm, y - 5 * mm, f'Fällig: {rechnung.faellig_am:%d.%m.%Y}')
    if s.get('uid'):
        c.drawRightString(190 * mm, y - 10 * mm, f"MWST-Nr.: {s['uid']}")

    yt = y - 40 * mm
    c.setStrokeColor(colors.lightgrey)
    c.line(20 * mm, yt + 5 * mm, 190 * mm, yt + 5 * mm)
    c.setFont('Helvetica', 10)
    c.drawString(20 * mm, yt,
                 f'Abonnement {rechnung.get_stufe_display()}, {rechnung.get_intervall_display().lower()}, '
                 f'{rechnung.periode_von:%d.%m.%Y}–{rechnung.periode_bis:%d.%m.%Y}')
    c.drawRightString(190 * mm, yt, _chf(rechnung.netto))
    c.drawString(20 * mm, yt - 5 * mm, f'{rechnung.einheiten} Einheiten bei Rechnungsstellung')
    zeile = yt - 12 * mm
    if rechnung.mwst_satz is not None:
        c.drawString(20 * mm, zeile, f'MWST {rechnung.mwst_satz:.1f} %')
        c.drawRightString(190 * mm, zeile, _chf(rechnung.mwst_betrag))
    else:
        c.setFont('Helvetica-Oblique', 9)
        c.drawString(20 * mm, zeile, 'MWST: Satz vom Betreiber nicht festgelegt, nicht ausgewiesen.')
        c.setFont('Helvetica', 10)
    if rechnung.platzhalter:
        c.setFont('Helvetica-Oblique', 9)
        c.drawString(20 * mm, zeile - 6 * mm, 'Platzhalterpreise: vom Betreiber noch nicht festgelegt.')
    c.setLineWidth(0.5)
    c.line(20 * mm, zeile - 12 * mm, 190 * mm, zeile - 12 * mm)
    c.setFont('Helvetica-Bold', 12)
    c.drawString(20 * mm, zeile - 19 * mm, 'Zu bezahlen')
    c.drawRightString(190 * mm, zeile - 19 * mm, _chf(rechnung.brutto))

    draw_qr_bill(c, iban, creditor, debtor, float(rechnung.brutto),
                 f'Abonnement {rechnung.nummer}', reference=rechnung.qr_referenz)
    c.showPage()
    c.save()
    puffer.seek(0)
    return puffer.read()

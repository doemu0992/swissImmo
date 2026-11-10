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
    from reportlab.lib.units import mm

    from core.services.dok_layout import DokCanvas
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
    # Briefkopf des Rechnungsstellers (der Plattform, nicht der Verwaltung), Adressfenster für die Organisation
    c = DokCanvas(puffer, absender=[s.get('name') or 'Plattform', s.get('strasse', ''),
                                    f"{s.get('plz', '')} {s.get('ort', '')}".strip()],
                  titel=f'Rechnung {rechnung.nummer}', ref=org.firma)
    c.setTitle(f'Rechnung {rechnung.nummer}')
    y = c.brief([debtor['name'], debtor['line1'], debtor['line2']], f'Datum: {rechnung.rechnungsdatum:%d.%m.%Y}',
                'Rechnung', untertitel=f'{rechnung.nummer} · ' + ('Zusatzrechnung zum Abonnement immoswiss' if rechnung.art == 'zusatz' else 'Abonnement immoswiss'))
    c.setFont('Helvetica', 10)
    c.drawRightString(190 * mm, c.hoehe - 93 * mm, f'Fällig: {rechnung.faellig_am:%d.%m.%Y}')
    if s.get('uid'):
        c.drawRightString(190 * mm, c.hoehe - 98 * mm, f"MWST-Nr.: {s['uid']}")

    yt = y - 14 * mm
    c.setStrokeColor(colors.lightgrey)
    c.line(20 * mm, yt + 5 * mm, 190 * mm, yt + 5 * mm)
    c.setFont('Helvetica', 10)
    periode = f'{rechnung.periode_von:%d.%m.%Y}–{rechnung.periode_bis:%d.%m.%Y}'
    if rechnung.positionen:
        # Grundpreis, zugebuchte Module und Rabatt je eine Zeile, wie bei der Rechnungsstellung festgehalten.
        from reportlab.lib.utils import simpleSplit
        letzte = yt + 5 * mm
        for i, position in enumerate(rechnung.positionen):
            text = f"{position['text']}, {periode}" if i == 0 and rechnung.art == 'abo' else position['text']
            # Lange Texte (z. B. Änderungen mit mehreren Modulen) umbrechen; der Betrag steht in der ersten Zeile rechts.
            zeilen = simpleSplit(text, 'Helvetica', 10, 135 * mm)
            letzte -= 5 * mm
            c.drawRightString(190 * mm, letzte, _chf(position['betrag']))
            for k, zeile_text in enumerate(zeilen):
                if k:
                    letzte -= 4.5 * mm
                c.drawString(20 * mm, letzte, zeile_text)
        if rechnung.einheiten and rechnung.art == 'abo':
            letzte -= 5 * mm
            c.drawString(20 * mm, letzte, f'{rechnung.einheiten} Einheiten bei Rechnungsstellung')
        zeile = letzte - 7 * mm
    else:
        c.drawString(20 * mm, yt,
                     f'Abonnement {rechnung.get_stufe_display()}, {rechnung.get_intervall_display().lower()}, {periode}')
        c.drawRightString(190 * mm, yt, _chf(rechnung.netto))
        if rechnung.einheiten:
            c.drawString(20 * mm, yt - 5 * mm, f'{rechnung.einheiten} Einheiten bei Rechnungsstellung')
        zeile = yt - 12 * mm
    if rechnung.mwst_satz is not None:
        c.drawString(20 * mm, zeile, f'MWST {rechnung.mwst_satz:.1f} %')
        c.drawRightString(190 * mm, zeile, _chf(rechnung.mwst_betrag))
    else:
        c.setFont('Helvetica-Oblique', 9)
        if getattr(settings, 'ABO_MWST_PFLICHTIG', True):
            c.drawString(20 * mm, zeile, 'MWST: Satz vom Betreiber nicht festgelegt, nicht ausgewiesen.')
        else:
            c.drawString(20 * mm, zeile, 'Nicht mehrwertsteuerpflichtig: keine MWST ausgewiesen.')
        c.setFont('Helvetica', 10)
    if rechnung.platzhalter:
        c.setFont('Helvetica-Oblique', 9)
        c.drawString(20 * mm, zeile - 6 * mm, 'Platzhalterpreise: vom Betreiber noch nicht festgelegt.')
    if rechnung.mahngebuehr:
        c.drawString(20 * mm, zeile - 9 * mm, 'Mahngebühr (2. Mahnung)')
        c.drawRightString(190 * mm, zeile - 9 * mm, _chf(rechnung.mahngebuehr))
    total = rechnung.brutto + rechnung.mahngebuehr
    c.setLineWidth(0.5)
    c.line(20 * mm, zeile - 12 * mm, 190 * mm, zeile - 12 * mm)
    c.setFont('Helvetica-Bold', 12)
    c.drawString(20 * mm, zeile - 19 * mm, 'Zu bezahlen')
    c.drawRightString(190 * mm, zeile - 19 * mm, _chf(total))

    draw_qr_bill(c, iban, creditor, debtor, float(total),
                 f'Abonnement {rechnung.nummer}', reference=rechnung.qr_referenz)
    c.showPage()
    c.save()
    puffer.seek(0)
    return puffer.read()

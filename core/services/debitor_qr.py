"""Erzeugt den QR-Einzahlungsschein (A4) für eine Debitorenrechnung.
Wiederverwendet von der Team-Ansicht und vom Mieterportal."""
import io


def generate_debitor_qr_pdf(rechnung):
    """Gibt die PDF-Bytes zurück oder None, wenn keine IBAN hinterlegt ist."""
    from reportlab.pdfgen import canvas as _canvas
    from reportlab.lib.pagesizes import A4 as _A4
    from reportlab.lib.units import mm as _mm
    from reportlab.lib import colors as _colors
    from crm.models import Verwaltung
    from core.utils.qr_code import draw_qr_bill

    r = rechnung
    lg = r.liegenschaft or (r.vertrag.einheit.liegenschaft if r.vertrag_id and r.vertrag.einheit_id else None)
    vw = Verwaltung.objects.first()
    mandant = lg.mandant if lg else None

    iban = (lg.iban if lg and lg.iban else (getattr(vw, 'iban', '') or '')).replace(' ', '')
    if not iban:
        return None

    if mandant:
        creditor = {'name': mandant.firma_oder_name, 'line1': mandant.strasse or '', 'line2': f"{mandant.plz or ''} {mandant.ort or ''}".strip()}
    elif vw:
        creditor = {'name': vw.firma, 'line1': vw.strasse or '', 'line2': f"{vw.plz or ''} {vw.ort or ''}".strip()}
    else:
        creditor = {'name': 'Immobilienverwaltung', 'line1': lg.strasse if lg else '', 'line2': f"{lg.plz} {lg.ort}" if lg else ''}

    mieter = r.vertrag.mieter if r.vertrag_id else None
    if mieter:
        debtor = {'name': mieter.display_name, 'line1': mieter.strasse or '', 'line2': f"{mieter.plz or ''} {mieter.ort or ''}".strip()}
    else:
        debtor = {'name': '—', 'line1': '', 'line2': ''}

    betrag = float(r.offener_betrag if r.status in ('offen', 'teilbezahlt') and r.offener_betrag > 0 else r.betrag)
    ref = r.qr_referenz or None

    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=_A4)
    c.setTitle(f"Rechnung {r.titel}")
    if vw and getattr(vw, 'logo', None):
        try:
            c.drawImage(vw.logo.path, 150 * _mm, 265 * _mm, width=40 * _mm, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
    c.setFillColor(_colors.black)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(20 * _mm, 270 * _mm, "Rechnung")
    c.setFont("Helvetica", 10)
    c.setFillColor(_colors.darkgrey)
    c.drawString(20 * _mm, 263 * _mm, r.titel)
    c.setFillColor(_colors.black)

    y = 245 * _mm
    c.setFont("Helvetica", 9); c.drawString(20 * _mm, y, "Rechnungsempfänger:")
    c.setFont("Helvetica-Bold", 11); c.drawString(20 * _mm, y - 6 * _mm, debtor['name'])
    c.setFont("Helvetica", 11)
    c.drawString(20 * _mm, y - 11 * _mm, debtor['line1'])
    c.drawString(20 * _mm, y - 16 * _mm, debtor['line2'])

    c.setFont("Helvetica", 10)
    c.drawRightString(190 * _mm, y, f"Datum: {r.datum.strftime('%d.%m.%Y')}")
    if r.faellig_am:
        c.drawRightString(190 * _mm, y - 5 * _mm, f"Fällig: {r.faellig_am.strftime('%d.%m.%Y')}")

    yt = y - 40 * _mm
    c.setStrokeColor(_colors.lightgrey); c.line(20 * _mm, yt + 5 * _mm, 190 * _mm, yt + 5 * _mm)
    c.setFont("Helvetica", 10)
    c.drawString(20 * _mm, yt, r.beschreibung or r.titel)
    c.drawRightString(190 * _mm, yt, f"CHF {float(r.betrag):,.2f}")
    c.setLineWidth(0.5); c.line(20 * _mm, yt - 4 * _mm, 190 * _mm, yt - 4 * _mm)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(20 * _mm, yt - 11 * _mm, "Zu bezahlen")
    c.drawRightString(190 * _mm, yt - 11 * _mm, f"CHF {betrag:,.2f}")

    draw_qr_bill(c, iban, creditor, debtor, betrag, r.titel, reference=ref)
    c.showPage(); c.save(); buf.seek(0)
    return buf.read()

"""Erzeugt den QR-Einzahlungsschein (A4) für eine Debitorenrechnung.
Wiederverwendet von der Team-Ansicht und vom Mieterportal."""
import logging
import io
from core.services.dokumentsprache import nur_deutsch, sprache_von

logger = logging.getLogger(__name__)


def schuldner_name(vertrag):
    """Schuldnername fürs QR-Feld. Bei 2-Personen-Verträgen beide Namen
    (max. 70 Zeichen laut QR-Norm — sonst nur der Hauptmieter)."""
    if not vertrag or not vertrag.mieter_id:
        return '—'
    name = vertrag.mieter.display_name
    zweiter = (vertrag.mitmieter.display_name if vertrag.mitmieter
               else (vertrag.mitmieter_name or '')).strip()
    if zweiter:
        kombi = f"{name} & {zweiter}"
        if len(kombi) <= 70:
            name = kombi
    return name


@nur_deutsch
def generate_debitor_qr_pdf(rechnung):
    """Gibt die PDF-Bytes zurück oder None, wenn keine IBAN hinterlegt ist."""
    from reportlab.lib.units import mm as _mm
    from reportlab.lib import colors as _colors
    from core.services.dok_layout import DokCanvas
    from core.utils.qr_code import draw_qr_bill

    r = rechnung
    lg = r.liegenschaft or (r.vertrag.einheit.liegenschaft if r.vertrag_id and r.vertrag.einheit_id else None)
    # Der Zahlungsempfaenger der QR-Rechnung. Von allen Stellen mit
    # `Organisation.objects.first()` war diese die folgenreichste: Steht dort
    # die falsche Verwaltung, traegt der Einzahlungsschein einen fremden
    # Empfaenger — im besten Fall weist die Bank ihn zurueck, im schlechteren
    # zahlt der Mieter an die falsche Adresse und die Forderung bleibt offen.
    vw = r.organisation
    eigentuemer = lg.eigentuemer if lg else None

    iban = (lg.iban if lg and lg.iban else (getattr(vw, 'iban', '') or '')).replace(' ', '')
    if not iban:
        return None

    if eigentuemer:
        creditor = {'name': eigentuemer.firma_oder_name, 'line1': eigentuemer.strasse or '',
                    'line2': f"{eigentuemer.plz or ''} {eigentuemer.ort or ''}".strip(),
                    'plz': eigentuemer.plz or '', 'ort': eigentuemer.ort or ''}
    elif vw:
        creditor = {'name': vw.firma, 'line1': vw.strasse or '',
                    'line2': f"{vw.plz or ''} {vw.ort or ''}".strip(),
                    'plz': vw.plz or '', 'ort': vw.ort or ''}
    else:
        creditor = {'name': 'Immobilienverwaltung', 'line1': lg.strasse if lg else '',
                    'line2': f"{lg.plz} {lg.ort}" if lg else '',
                    'plz': (lg.plz if lg else ''), 'ort': (lg.ort if lg else '')}

    mieter = r.vertrag.mieter if r.vertrag_id else None
    if mieter:
        debtor = {'name': schuldner_name(r.vertrag), 'line1': mieter.strasse or '',
                  'line2': f"{mieter.plz or ''} {mieter.ort or ''}".strip(),
                  'plz': mieter.plz or '', 'ort': mieter.ort or ''}
    else:
        debtor = {'name': '—', 'line1': '', 'line2': ''}

    betrag = (r.offener_betrag if r.status in ('offen', 'teilbezahlt') and r.offener_betrag > 0 else r.betrag)
    ref = r.qr_referenz or None

    buf = io.BytesIO()
    c = DokCanvas(buf, organisation=vw, absender=[creditor['name'], creditor['line1'], creditor['line2']],
                  titel=f"Rechnung {r.titel}", ref=debtor['name'])
    c.setTitle(f"Rechnung {r.titel}")
    y = c.brief([debtor['name'], debtor['line1'], debtor['line2']], f"Datum: {r.datum.strftime('%d.%m.%Y')}",
                "Rechnung", untertitel=r.titel)
    c.setFillColor(_colors.black)

    c.setFont("Helvetica", 10)
    if r.faellig_am:
        c.drawRightString(190 * _mm, c.hoehe - 93 * _mm, f"Fällig: {r.faellig_am.strftime('%d.%m.%Y')}")

    yt = y - 14 * _mm
    c.setStrokeColor(_colors.lightgrey); c.line(20 * _mm, yt + 5 * _mm, 190 * _mm, yt + 5 * _mm)
    def _chf(wert):
        return f"CHF {float(wert):,.2f}".replace(",", "'")

    mwst = r.mwst_betrag or 0
    c.setFont("Helvetica", 10)
    c.drawString(20 * _mm, yt, r.beschreibung or r.titel)
    if mwst > 0:
        # Steuerpflichtig vermietet (Option Art. 22 MWSTG): Netto, Satz, MWST und
        # Brutto stehen einzeln auf der Rechnung. Wohnraum läuft nie in diesen
        # Zweig (mwst_betrag = 0) und weist keine MWST aus.
        c.drawString(20 * _mm, yt - 7 * _mm, "Nettobetrag")
        c.drawRightString(190 * _mm, yt - 7 * _mm, _chf(r.netto_betrag))
        c.drawString(20 * _mm, yt - 12 * _mm, f"MWST {r.mwst_satz:.1f} %")
        c.drawRightString(190 * _mm, yt - 12 * _mm, _chf(mwst))
        c.setLineWidth(0.5); c.line(20 * _mm, yt - 15 * _mm, 190 * _mm, yt - 15 * _mm)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20 * _mm, yt - 20 * _mm, "Bruttobetrag (inkl. MWST)")
        c.drawRightString(190 * _mm, yt - 20 * _mm, _chf(r.betrag))
        uid = getattr(vw, 'mwst_uid', '') or ''
        if uid:
            c.setFont("Helvetica", 9)
            c.drawRightString(190 * _mm, c.hoehe - 98 * _mm, f"MWST-Nr.: {uid}")
        yt -= 20 * _mm
    else:
        c.drawRightString(190 * _mm, yt, _chf(r.betrag))
    c.setLineWidth(0.5); c.line(20 * _mm, yt - 4 * _mm, 190 * _mm, yt - 4 * _mm)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(20 * _mm, yt - 11 * _mm, "Zu bezahlen")
    c.drawRightString(190 * _mm, yt - 11 * _mm, _chf(betrag))

    # Der Zahlteil folgt der Sprache des Mieters (D11), auch wenn der Brief darüber deutsch bleibt.
    draw_qr_bill(c, iban, creditor, debtor, betrag, r.titel, reference=ref, sprache=sprache_von(mieter))
    c.showPage(); c.save(); buf.seek(0)
    return buf.read()

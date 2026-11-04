import logging
from crm.models import Organisation, Mieter
from portfolio.models import Liegenschaft
from rentals.models import Mietvertrag, Leerstand
from finance.models import AbrechnungsPeriode

import io
import datetime
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.utils.translation import gettext
from core.auth import rolle_erforderlich, ROLLE_VERWALTER, ROLLE_SACHBEARBEITER, ROLLE_LESEZUGRIFF

# Profi-Tools
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors

from decimal import Decimal

from core.services.dok_layout import LINKS, DokCanvas
from core.utils.billing import hole_abrechnung
from core.utils.qr_code import draw_qr_bill, ist_qr_iban, qrr_referenz, zahlteil_zeichnen

logger = logging.getLogger(__name__)


# ==========================================
# 1. QR RECHNUNG FÜR MIETZINS
# ==========================================

def format_iban(iban):
    if not iban: return ""
    iban = iban.replace(" ", "")
    return " ".join(iban[i:i+4] for i in range(0, len(iban), 4))

def qr_datenblock(iban, gl_name, gl_zeile1, gl_zeile2, sd_name, sd_zeile1, sd_zeile2,
                  betrag, ref_typ, ref_val, mitteilung):
    """Datenblock des Swiss QR Codes mit STRUKTURIERTEN Adressen («S»).

    Die kombinierte Adresse («K») wird mit dem SIC-Release vom 13.11.2026 abgewiesen
    (siehe `core.utils.qr_code.adressblock`)."""
    from core.utils.qr_code import adressblock
    return "\n".join([
        "SPC", "0200", "1", iban,
        *adressblock({'name': gl_name, 'line1': gl_zeile1, 'line2': gl_zeile2}),
        "", "", "", "", "", "", "", f"{betrag:.2f}", "CHF",
        *adressblock({'name': sd_name, 'line1': sd_zeile1, 'line2': sd_zeile2}, pflicht=False),
        ref_typ, ref_val, mitteilung, "EPD", ""
    ])


@rolle_erforderlich(ROLLE_VERWALTER, ROLLE_SACHBEARBEITER)
def qr_rechnung_pdf(request, vertrag_id):
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)
    einheit = vertrag.einheit
    liegenschaft = einheit.liegenschaft
    mieter = vertrag.mieter
    eigentuemer = liegenschaft.eigentuemer
    verwaltung = vertrag.organisation

    errors = []
    if not liegenschaft.iban: errors.append(f"Liegenschaft hat keine IBAN.")
    if not mieter.strasse or not mieter.plz or not mieter.ort: errors.append(f"Mieter Adresse unvollständig.")
    if errors: return HttpResponse(f"Fehler:<br>- " + "<br>- ".join(errors), status=400)

    raw_iban = liegenschaft.iban.replace(" ", "")
    total_betrag = vertrag.netto_mietzins + vertrag.nebenkosten

    creditor_name = eigentuemer.firma_oder_name if eigentuemer else "Immobilienverwaltung"
    creditor_line1 = liegenschaft.strasse
    creditor_line2 = f"{liegenschaft.plz} {liegenschaft.ort}"

    debtor_name = f"{mieter.vorname} {mieter.nachname}"
    debtor_line1 = mieter.strasse
    debtor_line2 = f"{mieter.plz} {mieter.ort}"

    monat_jahr = request.GET.get('monat', datetime.date.today().strftime('%m/%Y'))
    mitteilung = f"Miete {monat_jahr} - {einheit.bezeichnung}"

    # Referenztyp bestimmen (SIX-Spec): QR-IBAN => QRR + Referenz, sonst NON.
    # Monatliche Mietrechnung ohne DebitorenRechnung: synthetische QRR aus Vertrag + YYYYMM.
    if ist_qr_iban(raw_iban):
        try:
            mm_str, yyyy_str = monat_jahr.split('/')
            monat_id = int(yyyy_str) * 100 + int(mm_str)
        except (ValueError, IndexError):
            monat_id = int(datetime.date.today().strftime('%Y%m'))
        ref_raw, _formatiert = qrr_referenz(vertrag.id, monat_id)
        ref_typ, ref_val = "QRR", ref_raw
    else:
        ref_typ, ref_val = "NON", ""

    qr_data = qr_datenblock(raw_iban, creditor_name, creditor_line1, creditor_line2,
                            debtor_name, debtor_line1, debtor_line2,
                            total_betrag, ref_typ, ref_val, mitteilung)

    buffer = io.BytesIO()
    c = DokCanvas(buffer, organisation=verwaltung, absender=[creditor_name, creditor_line1, creditor_line2],
                  titel="Mietrechnung", ref=monat_jahr)
    c.setTitle(f"Mietrechnung {monat_jahr}")
    # Der Zahlteil unten (von Hand gezeichnet, Swiss QR Bill) füllt die untere Blatthälfte: keine Fusszeile.
    c.ohne_fuss()

    # Rechnungsempfänger im Fenster, Datum und Betreff: gemeinsames Briefgerüst
    y_start = c.brief([debtor_name, debtor_line1, debtor_line2],
                      f"Datum: {datetime.date.today().strftime('%d.%m.%Y')}", "Mietrechnung",
                      untertitel=f"Monat: {monat_jahr}")

    c.setFillColor(colors.black)
    c.setFont("Helvetica", 9)
    c.drawString(20*mm, y_start, "Objekt / Details:")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20*mm, y_start - 6*mm, f"{einheit.liegenschaft.strasse}")
    c.drawString(20*mm, y_start - 11*mm, f"{einheit.bezeichnung}")

    y_tab = y_start - 25*mm
    c.setStrokeColor(colors.lightgrey)
    c.line(20*mm, y_tab + 4*mm, 190*mm, y_tab + 4*mm)
    c.setFont("Helvetica", 10)
    c.drawString(20*mm, y_tab, "Nettomiete")
    c.drawRightString(190*mm, y_tab, f"CHF {vertrag.netto_mietzins:,.2f}".replace(",", "'"))
    c.drawString(20*mm, y_tab - 6*mm, "Nebenkosten")
    c.drawRightString(190*mm, y_tab - 6*mm, f"CHF {vertrag.nebenkosten:,.2f}".replace(",", "'"))
    c.setLineWidth(0.5)
    c.line(20*mm, y_tab - 10*mm, 190*mm, y_tab - 10*mm)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(20*mm, y_tab - 16*mm, "Totalbetrag")
    c.drawRightString(190*mm, y_tab - 16*mm, f"CHF {total_betrag:,.2f}".replace(",", "'"))

    # Zahlteil und Empfangsschein: eine gemeinsame Darstellung nach Style Guide (core.utils.qr_code).
    # Der Datenteil oben bleibt, wie er ist; gezeichnet wird nur.
    zahlteil_zeichnen(
        c, qr_data=qr_data, iban=raw_iban,
        creditor={'name': creditor_name, 'line1': creditor_line1, 'line2': creditor_line2},
        debtor={'name': debtor_name, 'line1': debtor_line1, 'line2': debtor_line2},
        amount=total_betrag, reason=mitteilung, ref_typ=ref_typ, ref_val=ref_val)

    c.showPage()
    c.save()
    buffer.seek(0)
    pdf_bytes = buffer.getvalue()
    # Ansehen legt nichts ab (ROUTE-01/18): Die QR-Rechnung kommt aus der
    # Sollstellung bzw. dem Debitoren-Beleg («QR erstellen», POST).
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    filename = f"QR_Rechnung_{mieter.nachname}_{monat_jahr.replace('/', '-')}.pdf"
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response


# ==========================================
# 2. NEBENKOSTEN ABRECHNUNG
# ==========================================

@rolle_erforderlich(ROLLE_VERWALTER, ROLLE_SACHBEARBEITER, ROLLE_LESEZUGRIFF)
def abrechnung_pdf_view(request, periode_id):
    periode = get_object_or_404(AbrechnungsPeriode, pk=periode_id)
    liegenschaft = periode.liegenschaft
    # Fehler h (NK-Wizard): Die Route rechnete live — nach dem Verbuchen druckte sie andere
    # Zahlen, als gebucht waren, sobald sich ein Beleg, eine Fläche oder ein Vertrag änderte.
    # `hole_abrechnung` liefert bei einer verbuchten Periode den eingefrorenen Stand.
    ergebnis = hole_abrechnung(periode)

    if 'error' in ergebnis:
        return HttpResponse(f"Fehler: {ergebnis['error']}")

    # Der Snapshot ist JSON: Beträge kommen als Text zurück.
    abrechnungen = [{**z, **{f: Decimal(str(z.get(f, 0))) for f in ('kosten_anteil', 'akonto', 'saldo')}}
                    for z in ergebnis.get('abrechnungen', [])]
    verwaltung = liegenschaft.organisation
    eigentuemer = liegenschaft.eigentuemer

    if not liegenschaft.iban:
        return HttpResponse("Fehler: Keine IBAN bei der Liegenschaft hinterlegt!", status=400)

    if verwaltung:
        creditor = {'name': verwaltung.firma, 'line1': verwaltung.strasse, 'line2': f"{verwaltung.plz} {verwaltung.ort}"}
    else:
        creditor = {'name': "Immobilienverwaltung", 'line1': liegenschaft.strasse, 'line2': f"{liegenschaft.plz} {liegenschaft.ort}"}

    buffer = io.BytesIO()
    c = DokCanvas(buffer, organisation=verwaltung,
                  absender=[creditor['name'], creditor['line1'], creditor['line2']],
                  titel=f"Nebenkostenabrechnung {periode.bezeichnung}", ref=liegenschaft.strasse)
    c.setTitle(f"NK {periode.bezeichnung}")

    for nr, row in enumerate(abrechnungen):
        if nr:
            c.neues_dokument()
        if row['typ'] in ('leerstand', 'eigentuemer'):
            if eigentuemer: debtor = {'name': eigentuemer.firma_oder_name, 'line1': eigentuemer.strasse, 'line2': f"{eigentuemer.plz} {eigentuemer.ort}"}
            else: debtor = {'name': "Eigentümer (Leerstand)", 'line1': '', 'line2': ''}
        else:
            debtor = {'name': row['name'], 'line1': liegenschaft.strasse, 'line2': f"{liegenschaft.plz} {liegenschaft.ort}"}

        # Adressfenster, Ort/Datum, Betreff: gemeinsames Briefgerüst (core/services/dok_layout.py)
        y0 = c.brief([debtor['name'], debtor['line1'], debtor['line2']],
                     f"{liegenschaft.ort}, {datetime.date.today().strftime('%d.%m.%Y')}",
                     f"Nebenkostenabrechnung: {periode.bezeichnung}")

        c.setFont("Helvetica", 10)
        c.drawString(LINKS, y0, f"Objekt: {row['einheit']}")
        c.drawString(LINKS, y0 - 5*mm, f"Abrechnungsperiode: {periode.start_datum.strftime('%d.%m.%Y')} bis {periode.ende_datum.strftime('%d.%m.%Y')}")

        if row.get('tage'): c.drawString(LINKS, y0 - 10*mm, f"Ihre Mietdauer: {row.get('tage')} Tage")

        y = y0 - 25*mm
        c.setFillColorRGB(0.9, 0.9, 0.9)
        c.rect(LINKS, y-2*mm, 170*mm, 8*mm, fill=1, stroke=0)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(LINKS + 5*mm, y, "Beschreibung")
        c.drawRightString(185*mm, y, "Betrag (CHF)")

        y -= 10*mm
        c.setFont("Helvetica", 10)
        c.drawString(LINKS + 5*mm, y, f"Ihr Anteil an den Gesamtkosten ({periode.bezeichnung})")
        c.drawRightString(185*mm, y, f"{row['kosten_anteil']:.2f}")
        y -= 6*mm

        if row['akonto'] > 0:
            c.drawString(LINKS + 5*mm, y, "Abzüglich Ihre Akontozahlungen")
            c.drawRightString(185*mm, y, f"- {row['akonto']:.2f}")
            y -= 8*mm

        c.line(LINKS, y, 190*mm, y)
        y -= 8*mm

        saldo = row['saldo']
        betrag_abs = abs(saldo)

        c.setFont("Helvetica-Bold", 12)
        if row['nachzahlung']:
            c.drawString(LINKS + 5*mm, y, "Nachzahlung zu Ihren Lasten:")
            text_info = "Bitte begleichen Sie den Betrag innert 30 Tagen."
        else:
            c.drawString(LINKS + 5*mm, y, "Guthaben zu Ihren Gunsten:")
            text_info = "Das Guthaben wird auf Ihr Konto überwiesen."

        c.drawRightString(185*mm, y, f"CHF {betrag_abs:.2f}")
        y -= 10*mm
        c.setFont("Helvetica", 10)
        c.drawString(LINKS + 5*mm, y, text_info)

        c.showPage()

        if row['nachzahlung'] and liegenschaft.iban:
            try:
                nk_ref = None
                if ist_qr_iban(liegenschaft.iban) and row.get('vertrag_id'):
                    nk_ref, _ = qrr_referenz(row['vertrag_id'], 900000 + (periode.id or 0))
                draw_qr_bill(c, liegenschaft.iban, creditor, debtor, betrag_abs,
                             f"NK {periode.bezeichnung} - {row['einheit']}", reference=nk_ref)
                c.showPage()
            except Exception as e:
                # Früher `print`: Die Abrechnung ging mit einer Nachzahlung OHNE
                # Einzahlungsschein hinaus. Jetzt Protokoll und eine sichtbare Absage.
                logger.exception("NK-Abrechnung: QR-Rechnung für Periode %s nicht erzeugt", periode.pk)
                return HttpResponse(
                    gettext("Fehler: Die QR-Rechnung für %(einheit)s konnte nicht erzeugt werden (%(fehler)s). "
                            "Das PDF wurde nicht ausgeliefert, damit keine Nachzahlung ohne Einzahlungsschein verschickt wird.")
                    % {'einheit': row['einheit'], 'fehler': e}, status=500)

    c.save()
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Abrechnung_{periode.bezeichnung}.pdf"'
    return response
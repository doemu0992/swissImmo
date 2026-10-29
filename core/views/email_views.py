from crm.models import Organisation, Mieter
from portfolio.models import Liegenschaft, Einheit
from rentals.models import Mietvertrag, Leerstand
from finance.models import AbrechnungsPeriode

import io
import logging
import datetime
from decimal import Decimal
from django.core.mail import EmailMultiAlternatives
from django.utils.translation import gettext
from django.template.loader import render_to_string
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from core.auth import rolle_erforderlich, log_aktion, ROLLE_VERWALTER, ROLLE_SACHBEARBEITER
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.http import require_POST

# ReportLab (PDF)
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors

# Eigene Imports
from core.utils.billing import berechne_abrechnung
from core.utils.qr_code import draw_qr_bill

logger = logging.getLogger(__name__)

# ==============================================================================
# HILFSFUNKTIONEN FÜR PDF-GENERIERUNG
# ==============================================================================

def get_aktueller_monat():
    """Gibt den aktuellen Monat und das Jahr auf Deutsch zurück (z.B. 'Mai 2026')"""
    monate = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
    heute = datetime.date.today()
    return f"{monate[heute.month - 1]} {heute.year}"

def draw_header(c, verwaltung):
    """ Zeichnet das Logo und die Absenderzeile oben """
    if not verwaltung: return
    if verwaltung.logo:
        try:
            c.drawImage(verwaltung.logo.path, 20*mm, 270*mm, height=15*mm, preserveAspectRatio=True, mask='auto')
        except: pass
    c.setFont("Helvetica", 8)
    c.drawRightString(190*mm, 280*mm, f"{verwaltung.firma} | {verwaltung.strasse} | {verwaltung.plz} {verwaltung.ort}")


def generate_single_pdf_bytes(periode, row, verwaltung, liegenschaft, vertrag):
    """ Erzeugt das NK-Abrechnung-PDF im Speicher (inkl. QR auf Seite 2) """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)

    if verwaltung:
        creditor = {'name': verwaltung.firma, 'line1': verwaltung.strasse,
                    'line2': f"{verwaltung.plz} {verwaltung.ort}",
                    'plz': verwaltung.plz or '', 'ort': verwaltung.ort or ''}
    else:
        creditor = {'name': "Immobilienverwaltung", 'line1': liegenschaft.strasse,
                    'line2': f"{liegenschaft.plz} {liegenschaft.ort}",
                    'plz': liegenschaft.plz or '', 'ort': liegenschaft.ort or ''}

    debtor = {'name': f"{vertrag.mieter.vorname} {vertrag.mieter.nachname}", 'line1': vertrag.mieter.strasse, 'line2': f"{vertrag.mieter.plz} {vertrag.mieter.ort}"} if vertrag else {'name': row['name'], 'line1': '', 'line2': ''}

    draw_header(c, verwaltung)
    c.setFont("Helvetica", 11); c.drawString(25*mm, 245*mm, debtor['name']); c.drawString(25*mm, 240*mm, debtor['line1']); c.drawString(25*mm, 235*mm, debtor['line2'])
    c.setFont("Helvetica", 10); c.drawRightString(190*mm, 245*mm, f"Datum: {datetime.date.today().strftime('%d.%m.%Y')}"); c.drawRightString(190*mm, 240*mm, f"Liegenschaft: {liegenschaft.ort}")
    c.setFont("Helvetica-Bold", 14); c.drawString(20*mm, 210*mm, f"Nebenkostenabrechnung: {periode.bezeichnung}")

    # Kostenauflistung...
    y = 170*mm
    c.setFillColorRGB(0.9, 0.9, 0.9); c.rect(20*mm, y-2*mm, 170*mm, 8*mm, fill=1, stroke=0); c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 10); c.drawString(25*mm, y, "Beschreibung"); c.drawRightString(185*mm, y, "Betrag (CHF)")
    y -= 10*mm; c.setFont("Helvetica", 10); c.drawString(25*mm, y, f"Kostenanteil"); c.drawRightString(185*mm, y, f"{row['kosten_anteil']:.2f}")
    y -= 6*mm; akonto = row.get('akonto', 0)
    if akonto > 0: c.drawString(25*mm, y, "Abzüglich Akonto Zahlungen"); c.drawRightString(185*mm, y, f"- {akonto:.2f}"); y -= 8*mm
    c.line(20*mm, y, 190*mm, y); y -= 8*mm; betrag = abs(row['saldo'])
    c.setFont("Helvetica-Bold", 12)
    label = "Nachzahlung zu Ihren Lasten:" if row['nachzahlung'] else "Guthaben zu Ihren Gunsten:"
    c.drawString(25*mm, y, label); c.drawRightString(185*mm, y, f"CHF {betrag:.2f}")

    c.showPage()
    if row['nachzahlung'] and liegenschaft.iban:
        try:
            draw_qr_bill(c, liegenschaft.iban, creditor, debtor, betrag, f"NK {periode.bezeichnung}")
            c.showPage()
        except Exception:
            # Früher `except: pass`: Die Abrechnung ging mit einer Nachzahlung OHNE
            # Einzahlungsschein hinaus, und niemand erfuhr davon. Jetzt steht der
            # Fehler im Protokoll und bricht die Erzeugung ab.
            logger.exception("NK-Abrechnung: QR-Rechnung für Periode %s nicht erzeugt", periode.pk)
            raise

    c.save(); buffer.seek(0)
    return buffer.getvalue()


def _aufstellung_zeichnen(c, positionen, betrag_str, verwaltung, vertrag):
    """Beilage zur 257d-Fristansetzung: jede verzugsbegründende Forderung mit Bezeichnung, Fälligkeit und
    offenem Betrag, darunter das Total. Beginnt eine neue Seite und läuft bei Bedarf auf weitere Seiten."""
    def kopf(fortsetzung):
        c.showPage()
        c.setFont("Helvetica-Bold", 12)
        c.drawString(25*mm, 270*mm, "Aufstellung der ausstehenden Beträge" + (" (Fortsetzung)" if fortsetzung else ""))
        c.setFont("Helvetica", 9)
        c.drawString(25*mm, 264*mm, f"Beilage zur Zahlungsaufforderung nach Art. 257d OR – {vertrag.einheit.bezeichnung}")
        c.setFont("Helvetica-Bold", 10)
        c.drawString(25*mm, 254*mm, "Bezeichnung")
        c.drawString(115*mm, 254*mm, "Fällig am")
        c.drawRightString(185*mm, 254*mm, "Betrag CHF")
        c.line(25*mm, 252*mm, 185*mm, 252*mm)
        return 246*mm

    y = kopf(False)
    c.setFont("Helvetica", 10)
    for bez, faellig, betrag in positionen:
        if y < 30*mm:
            y = kopf(True)
            c.setFont("Helvetica", 10)
        c.drawString(25*mm, y, str(bez)[:60])
        c.drawString(115*mm, y, f"{faellig:%d.%m.%Y}")
        c.drawRightString(185*mm, y, f"{betrag:.2f}")
        y -= 6*mm
    if y < 40*mm:
        y = kopf(True)
    c.line(25*mm, y + 3*mm, 185*mm, y + 3*mm)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(25*mm, y - 3*mm, "Total ausstehend")
    c.drawRightString(185*mm, y - 3*mm, f"{betrag_str}")


# 🔥 VERBESSERT: Hilfsfunktion für das kombinierte PDF (Brief S1 + QR S2)
def generate_mahnung_combined_pdf_bytes(vertrag, verwaltung, monat_str, betrag_str, heute,
                                        empfaenger=None, reference=None,
                                        gebuehr=None, gebuehr_reference=None,
                                        positionen=None):
    """257d-Zahlungsaufforderung mit Kuendigungsandrohung (+ QR-Rechnung).

    `gebuehr` (> 0): Die Mahngebühr der Stufe. Sie steht als eigener Absatz im Brief und
    bekommt einen SEPARATEN QR-Einzahlungsschein (letzte Seite, `gebuehr_reference` = QRR
    der Gebührenforderung). Sie ist bewusst NICHT im Betrag der Fristansetzung und nicht auf
    dem ersten Einzahlungsschein: Art. 257d OR nennt nur Mietzinse und Nebenkosten
    (siehe core/services/zahlungsverzug.py).
    positionen (optional): [(Bezeichnung, fällig am, Betrag), …] — jede verzugsbegründende Forderung
    einzeln mit Monat und Betrag (Audit MIET-02). Bis zu drei Positionen stehen im Brieftext, mehr auf einer
    Beilage («Aufstellung der ausstehenden Beträge») vor dem Einzahlungsschein. Ohne Angabe steht wie bisher
    nur `monat_str`/`betrag_str` im Text.

    UNTERSCHRIFT (Audit MIET-03): Das Schreiben trägt KEIN Unterschriftsbild. Die Fristansetzung mit
    Kündigungsandrohung verlangt Schriftlichkeit (Art. 257d Abs. 1 OR, Art. 13/14 OR: eigenhändige
    Unterschrift); die mechanische Nachbildung nach Art. 14 Abs. 2 OR genügt nur, wo sie im Verkehr üblich
    ist, und Art. 269d Abs. 4 OR gilt nur für Mietzinserhöhungen. Das PDF lässt die Linie darum frei und
    sagt es: «Eigenhändige Unterschrift». Ausgedruckt wird es vor dem Versand von Hand unterschrieben.
    empfaenger (optional): {firma, name, strasse, ort_line, nachname, anrede} —
    ueberschreibt den Empfaenger fuer separat adressierte Kopien (Art. 266n OR:
    Familienwohnung/Mitmieter). Ohne Override: vertrag.mieter."""
    # Gegen einen Stockwerkeigentümer gibt es keine Kündigungsandrohung (Art. 257d OR gilt nur für Mieter).
    from core.services.zahlungsverzug import pruefe_kein_eigentuemer
    pruefe_kein_eigentuemer(vertrag)
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    _e = empfaenger or {}
    r_firma   = _e.get('firma')   if empfaenger else getattr(vertrag.mieter, 'firma', None)
    r_name    = _e.get('name')    if empfaenger else f"{vertrag.mieter.vorname} {vertrag.mieter.nachname}"
    r_strasse = _e.get('strasse') if empfaenger else vertrag.mieter.strasse
    r_ortline = _e.get('ort_line') if empfaenger else f"{vertrag.mieter.plz} {vertrag.mieter.ort}"
    r_nachn   = _e.get('nachname') if empfaenger else vertrag.mieter.nachname
    r_anrede  = _e.get('anrede')  if empfaenger else getattr(vertrag.mieter, 'anrede', '')

    # --- SEITE 1: DAS JURISTISCHE SCHREIBEN ---
    left_margin = 25*mm
    right_window_margin = 120*mm

    c.setFont("Helvetica-Bold", 10)
    if verwaltung:
        c.drawString(left_margin, 280*mm, verwaltung.firma)
        c.setFont("Helvetica", 9)
        c.drawString(left_margin, 275*mm, f"{verwaltung.strasse}, {verwaltung.plz} {verwaltung.ort}")

    y_addr = 250*mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(right_window_margin, y_addr, "EINSCHREIBEN")

    y_addr -= 8*mm
    c.setFont("Helvetica", 11)

    firma_name = r_firma
    if firma_name:
        c.drawString(right_window_margin, y_addr, firma_name); y_addr -= 5*mm

    c.drawString(right_window_margin, y_addr, r_name)
    c.drawString(right_window_margin, y_addr-5*mm, r_strasse or '')
    c.drawString(right_window_margin, y_addr-10*mm, r_ortline)

    c.setFont("Helvetica", 10); c.drawString(left_margin, 210*mm, f"{verwaltung.ort if verwaltung else 'Ort'}, {heute.strftime('%d.%m.%Y')}")
    c.setFont("Helvetica-Bold", 12); c.drawString(left_margin, 195*mm, f"Zahlungsverzug gemäss Art. 257d OR – Kündigungsandrohung")
    c.setFont("Helvetica-Bold", 10); c.drawString(left_margin, 189*mm, f"Mietobjekt: {vertrag.einheit.bezeichnung}, {vertrag.einheit.liegenschaft.strasse}")

    c.setFont("Helvetica", 11); text_y = 175*mm
    salutation = "Sehr geehrte Damen und Herren,"
    if r_anrede == "Herr": salutation = f"Sehr geehrter Herr {r_nachn},"
    elif r_anrede == "Frau": salutation = f"Sehr geehrte Frau {r_nachn},"
    c.drawString(left_margin, text_y, salutation); text_y -= 10*mm

    positionen = list(positionen or [])
    if len(positionen) <= 1:
        einleitung = [
            f"Bei der Kontrolle unserer Mietzinseingänge mussten wir leider feststellen, dass für den",
            f"Monat {monat_str} noch ein Betrag von CHF {betrag_str} ausstehend ist.", ""]
    elif len(positionen) <= 3:
        einleitung = [
            "Bei der Kontrolle unserer Mietzinseingänge mussten wir leider feststellen, dass folgende",
            "fällige Mietzinse und Nebenkosten ausstehend sind:",
            *[f"   {bez}, fällig am {faellig:%d.%m.%Y}: CHF {betrag:.2f}" for bez, faellig, betrag in positionen],
            f"   Total: CHF {betrag_str}", ""]
    else:
        einleitung = [
            "Bei der Kontrolle unserer Mietzinseingänge mussten wir leider feststellen, dass mehrere",
            f"fällige Mietzinse und Nebenkosten ausstehend sind, insgesamt CHF {betrag_str}.",
            "Die einzelnen Monate und Beträge stehen in der beiliegenden Aufstellung.", ""]
    lines = [
        *einleitung,
        "Gestützt auf Art. 257d des Schweizerischen Obligationenrechts (OR) setzen wir Ihnen",
        "hiermit eine formelle Zahlungsfrist von", "",
        "30 TAGEN", "",
        f"ab Erhalt dieses Schreibens an, um den oben genannten Betrag zu begleichen.", "",
        "KÜNDIGUNGSANDROHUNG:",
        "Sollte die vollständige Zahlung nicht innert dieser Frist bei uns eintreffen, werden wir",
        "das Mietverhältnis gestützt auf Art. 257d Abs. 2 OR ausserordentlich kündigen.", "",
        *([f"Für diese Mahnung stellen wir Ihnen eine Mahngebühr von CHF {gebuehr:.2f} in Rechnung.",
           "Bitte bezahlen Sie diese mit dem separaten Einzahlungsschein auf der letzten Seite.", ""]
          if gebuehr and gebuehr > 0 else []),
        "Sollte sich Ihre Zahlung mit diesem Schreiben gekreuzt haben, bitten wir Sie,",
        "dieses Schreiben als gegenstandslos zu betrachten.", "",
        "Freundliche Grüsse", "", "", "__________________________",
        "Eigenhändige Unterschrift",
        f"{verwaltung.firma if verwaltung else 'Die Vermieterschaft'}"
    ]

    # Verdichten, wenn die Positionen den Platz knapp machen (Aufstand bis ins Blattende vermeiden).
    zeilenhoehe = 5.5 * mm if len(lines) <= 27 else 4.6 * mm
    for line in lines:
        if "30 TAGEN" in line or "KÜNDIGUNGSANDROHUNG" in line: c.setFont("Helvetica-Bold", 11)
        elif line == "Eigenhändige Unterschrift": c.setFont("Helvetica-Oblique", 8)
        else: c.setFont("Helvetica", 11)
        c.drawString(left_margin, text_y, line); text_y -= zeilenhoehe

    # Kein Unterschriftsbild: Ein Faksimile macht aus dem Ausdruck ein Schreiben, das unterschrieben aussieht,
    # es aber nicht ist (Art. 14 OR). Die Linie bleibt frei für die eigenhändige Unterschrift.

    # --- BEILAGE: AUFSTELLUNG DER AUSSTEHENDEN BETRÄGE ---
    if len(positionen) > 3:
        _aufstellung_zeichnen(c, positionen, betrag_str, verwaltung, vertrag)

    # --- SEITE 2: DIE QR-RECHNUNG ---
    # QR-Einzahlungsschein: IBAN der Liegenschaft, sonst die der Verwaltung
    # (Kreditor ist die Verwaltung). Ohne diesen Fallback fehlte die QR-Seite,
    # wenn die IBAN nur auf der Verwaltung hinterlegt ist (Nutzer-Bug).
    iban = getattr(vertrag.einheit.liegenschaft, 'iban', None) or getattr(verwaltung, 'iban', None)
    if iban:
        try:
            c.showPage()
            betrag_float = float(str(betrag_str).replace(',', '.'))

            if verwaltung:
                creditor = {'name': verwaltung.firma, 'line1': verwaltung.strasse,
                    'line2': f"{verwaltung.plz} {verwaltung.ort}",
                    'plz': verwaltung.plz or '', 'ort': verwaltung.ort or ''}
            else:
                creditor = {'name': "Verwaltung", 'line1': vertrag.einheit.liegenschaft.strasse, 'line2': f"{vertrag.einheit.liegenschaft.plz} {vertrag.einheit.liegenschaft.ort}"}

            m_name = firma_name if firma_name else r_name
            debtor = {'name': m_name, 'line1': r_strasse or '', 'line2': r_ortline}

            # `reference`: QRR der gemahnten Forderung. Ohne sie wäre die QR-Rechnung
            # mit QR-IBAN nach SIX-Spezifikation ungültig (NON + QR-IBAN) und die
            # Zahlung im camt-Import nicht zuordenbar. Mahnt das Schreiben mehrere
            # Forderungen (`reference` leer), trägt der Schein die Sammelreferenz
            # des Vertrags — gültig, aber keiner Einzelforderung zugeschlagen.
            from core.utils.qr_code import ist_qr_iban, sammelreferenz
            if ist_qr_iban(iban):
                reference = reference or sammelreferenz(vertrag.id)
                gebuehr_reference = gebuehr_reference or sammelreferenz(vertrag.id)
            draw_qr_bill(c, iban, creditor, debtor, betrag_float,
                         f"Mahnung {monat_str} {vertrag.einheit.bezeichnung}",
                         reference=reference)
            # SEPARATER Einzahlungsschein für die Mahngebühr — eigener Betrag, eigene Referenz.
            if gebuehr and gebuehr > 0:
                c.showPage()
                draw_qr_bill(c, iban, creditor, debtor, float(gebuehr),
                             f"Mahngebühr {monat_str} {vertrag.einheit.bezeichnung}",
                             reference=gebuehr_reference)
        except Exception:
            # Früher `except: pass`: Das Schreiben ging OHNE Einzahlungsschein
            # hinaus, und niemand erfuhr davon — bei einer Zahlungsaufforderung
            # nach Art. 257d OR ein Mangel mit Folgen. Jetzt steht der Fehler im
            # Protokoll und bricht die Erzeugung ab.
            logger.exception("Mahnung/257d: QR-Rechnung für Vertrag %s nicht erzeugt", vertrag.pk)
            raise

    c.save(); buffer.seek(0)
    return buffer.getvalue()


# ==============================================================================
# VIEWS
# ==============================================================================

@rolle_erforderlich(ROLLE_VERWALTER)
def send_abrechnung_email_view(request, periode_id):
    """Nie fertiggebaut — und darum ein 404 statt eines Serverfehlers.

    Der Rumpf war `pass`. Eine View, die None zurückgibt, quittiert JEDEN
    Aufruf mit einem 500 (`didn't return an HttpResponse object`); im
    Isolations-Registrylauf sah das aus wie ein Fehlschlag der
    Mandantentrennung und war in Wahrheit eine tote Route.

    Der Admin-Knopf, der hierher zeigte (`finance/admin.py`), ist entfernt.
    Die Route bleibt eingetragen, damit alte Lesezeichen ein ehrliches 404
    statt eines Serverfehlers erhalten, bis der Versand gebaut ist.
    """
    from django.http import Http404
    raise Http404('Abrechnungsversand ist nicht implementiert.')


# Nur POST: Die Ansicht verschickt eine Mahnung mit Kündigungsandrohung und legt
# sie in der Akte ab. Als GET genügte ein Link-Prefetch oder ein Crawler dafür.
@rolle_erforderlich(ROLLE_VERWALTER)
@require_POST
def send_mahnung_email_view(request, vertrag_id):
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)
    # Absender der Mahnung: die Verwaltung DIESES Vertrags — an ihrem Briefkopf
    # haengt nach OR 257d die Kuendigungsandrohung.
    verwaltung = vertrag.organisation

    # 🌟 NEU: Dynamischer Monat als Default
    monat_str = request.POST.get('monat') or get_aktueller_monat()
    betrag_str = request.POST.get('betrag', '0.00')

    if not vertrag.mieter.email:
        messages.error(request, gettext('Mieter hat keine E-Mail.')); return redirect(request.META.get('HTTP_REFERER', '/admin/'))

    heute = datetime.date.today()
    from core.services.ablage import ablage_mahnung

    # Aus der Mahnliste (`rechnung` + `stufe`): die Kopie der MAHNUNG dieser Stufe,
    # mit Monat und offenem Betrag der Forderung. Sie ist keine 257d-Androhung.
    rid, stufe_roh = request.POST.get('rechnung'), request.POST.get('stufe')
    if rid and stufe_roh:
        from finance.models import DebitorenRechnung
        from core.services.mahnbrief import forderungs_monat, mahnbrief_pdf, titel_fuer
        from core.services.mahnstufen import eigentuemer_von_rechnung, mahnstufen_config
        rechnung = get_object_or_404(DebitorenRechnung, pk=rid, vertrag=vertrag)
        if rechnung.offener_betrag <= 0:
            messages.error(request, gettext('Diese Forderung ist nicht mehr offen.'))
            return redirect(request.META.get('HTTP_REFERER', '/admin/'))
        # Nur Stufen, die die Verwaltung eingerichtet hat (crm.MahnStufe); sonst die erste.
        stufen = sorted(mahnstufen_config(eigentuemer_von_rechnung(rechnung),
                                          rechnung.organisation), key=lambda x: x['stufe'])
        try:
            stufe = int(stufe_roh)
        except ValueError:
            stufe = None
        cfg = next((x for x in stufen if x['stufe'] == stufe), None) or (stufen[0] if stufen else None)
        stufe = cfg['stufe'] if cfg else 1
        monat_str = forderungs_monat(rechnung)
        betrag_str = f"{rechnung.offener_betrag:.2f}"
        pdf_bytes = mahnbrief_pdf(
            vertrag, verwaltung, stufe=stufe, monat=monat_str, betrag=betrag_str,
            datum=heute, gebuehr=cfg['gebuehr'] if cfg else None,
            letzte_stufe=bool(cfg and cfg['kuendigung']), rechnung=rechnung)
        # Die Kopie geht per E-Mail an den Mieter: Er darf sie im Portal sehen.
        ablage_mahnung(vertrag, stufe=stufe, datum=heute, pdf_bytes=pdf_bytes,
                       im_portal_sichtbar=True)
        objekt = f"{vertrag.einheit.bezeichnung} ({vertrag.einheit.liegenschaft.strasse})"
        titel = titel_fuer(vertrag, stufe, bool(cfg and cfg['kuendigung']))
        email = EmailMultiAlternatives(
            subject=f"{titel}: {objekt}",
            body=(f"Guten Tag, im Anhang finden Sie die {titel} "
                  f"für {monat_str} über CHF {betrag_str} (Kopie; das Original erhalten "
                  f"Sie auf dem Postweg)."),
            from_email=settings.DEFAULT_FROM_EMAIL, to=[vertrag.mieter.email])
        email.attach(f"Mahnung_{stufe}_{monat_str.replace(' ', '_')}.pdf", pdf_bytes, 'application/pdf')
        email.send()
        log_aktion(request, f"{stufe}. Mahnung als Kopie versendet", str(vertrag),
                   f"an {vertrag.mieter.email}, {monat_str}, CHF {betrag_str}")
        messages.success(request, '✅ ' + gettext('Mahnung inkl. QR-Rechnung an %(email)s gesendet.') % {'email': vertrag.mieter.email})
        return redirect(request.META.get('HTTP_REFERER', '/admin/'))

    # 257d-Kündigungsandrohung: Betrag muss ein positiver Betrag sein — die Vorgabe
    # '0.00' liess eine Kündigungsandrohung über CHF 0.00 zu.
    try:
        _betrag_ok = Decimal(str(betrag_str).replace(',', '.')) > 0
    except Exception:
        _betrag_ok = False
    if not _betrag_ok:
        messages.error(request, gettext('Ungültiger oder fehlender Betrag — Mahnung nicht versendet.'))
        return redirect(request.META.get('HTTP_REFERER', '/admin/'))

    pdf_bytes = generate_mahnung_combined_pdf_bytes(vertrag, verwaltung, monat_str, betrag_str, heute)
    # Dasselbe PDF, das der Mieter erhält, gehört in die Akte — sonst lässt sich
    # später nicht belegen, WAS zugestellt wurde.
    ablage_mahnung(vertrag, monat=monat_str, betrag=betrag_str, datum=heute,
                   pdf_bytes=pdf_bytes, zugang_pflichtig=True, im_portal_sichtbar=True)

    firma_name = getattr(vertrag.mieter, 'firma', None)
    anzeige_name = firma_name if firma_name else f"{vertrag.mieter.vorname} {vertrag.mieter.nachname}"

    context = {
        'firma_name': verwaltung.firma if verwaltung else 'Ihre Verwaltung',
        'logo_url': request.build_absolute_uri(verwaltung.logo.url) if verwaltung and verwaltung.logo else "",
        'mieter_name': anzeige_name,
        'objekt_name': f"{vertrag.einheit.bezeichnung} ({vertrag.einheit.liegenschaft.strasse})",
        'monat': monat_str, 'betrag': betrag_str,
    }

    html_content = render_to_string('emails/email_mahnung.html', context)
    email = EmailMultiAlternatives(
        subject=f"Kopie: Mahnung mit Kündigungsandrohung (Art. 257d OR) — Original folgt per Einschreiben: {context['objekt_name']}",
        body=(f"Guten Tag, im Anhang finden Sie eine KOPIE der Mahnung für {monat_str}. "
              f"Die massgebende Fristansetzung erhalten Sie zusätzlich per Einschreiben."),
        from_email=settings.DEFAULT_FROM_EMAIL, to=[vertrag.mieter.email],
    )
    email.attach_alternative(html_content, "text/html")
    email.attach(f"Mahnung_{monat_str.replace(' ','_')}.pdf", pdf_bytes, 'application/pdf')
    email.send()

    # Schriftform (Art. 13 OR): Die E-Mail ist nur die Kopie. Bis die Fristansetzung per
    # Einschreiben rausgegangen ist (`fw_verzug_257d`), steht eine Pendenz im Arbeitsvorrat.
    from core.models import Pendenz
    quelle = f'257d-einschreiben:{vertrag.pk}'
    if not Pendenz.objects.filter(vertrag=vertrag, quelle=quelle, erledigt=False).exists():
        Pendenz.objects.create(
            titel=f'Art. 257d: Original per Einschreiben versenden – {vertrag.mieter.display_name}',
            beschreibung=(f'Per E-Mail ging nur eine Kopie der Mahnung mit Kündigungsandrohung an '
                          f'{vertrag.mieter.email} (Monat {monat_str}, CHF {betrag_str}). Die Frist nach '
                          f'Art. 257d OR beginnt erst mit dem Zugang des eingeschriebenen Briefes: '
                          f'Fristansetzung jetzt mit Sendungsnummer erfassen.'),
            kategorie='frist', faellig_am=heute + datetime.timedelta(days=2), vertrag=vertrag,
            liegenschaft=vertrag.einheit.liegenschaft if vertrag.einheit_id else None,
            quelle=quelle, erstellt_von=request.user if request.user.is_authenticated else None)
    log_aktion(request, "Mahnung (Kopie) per E-Mail versendet (Art. 257d OR)", str(vertrag),
               f"an {vertrag.mieter.email}, Monat {monat_str}, CHF {betrag_str} — Original per Einschreiben ausstehend")
    messages.success(request, '✅ ' + gettext('Mahnung inkl. QR-Rechnung an %(email)s gesendet.') % {'email': vertrag.mieter.email})
    messages.warning(request, gettext('Das war nur die Kopie. Rechtsgültig ist der eingeschriebene Brief — die Fristansetzung jetzt erfassen, sonst läuft keine Frist.'))
    return redirect(request.META.get('HTTP_REFERER', '/admin/'))


@rolle_erforderlich(ROLLE_VERWALTER, ROLLE_SACHBEARBEITER)
def generate_mahnung_pdf_view(request, vertrag_id):
    vertrag = get_object_or_404(Mietvertrag, pk=vertrag_id)
    verwaltung = vertrag.organisation

    # 🌟 NEU: Dynamischer Monat als Default
    monat_str = request.GET.get('monat') or request.POST.get('monat') or get_aktueller_monat()

    default_betrag = f"{vertrag.netto_mietzins + vertrag.nebenkosten:.2f}"
    betrag_str = request.GET.get('betrag') or request.POST.get('betrag', default_betrag)

    heute = datetime.date.today()

    # VORSCHAU: Dieser Aufruf (GET) legt nichts ab und schreibt nichts (ROUTE-01).
    # Vorher landete schon das blosse Öffnen der 257d-Fassung in der Vertragsakte —
    # im Mieterportal sichtbar, ohne dass je etwas versandt worden wäre. Abgelegt
    # wird beim Versand (`send_mahnung_email_view`, POST) und beim Erfassen der
    # Mahnung im Mahnwesen.

    # MAHNSTUFE AUS DEM MAHNWESEN (`?rechnung=<id>&stufe=<n>`): Das Schreiben der
    # Stufe — mit Monat und offenem Betrag DER FORDERUNG, nicht frei eingebbar.
    # Nur der Aufruf ohne Stufe (Vertragsseite, Fristansetzung) liefert die
    # 257d-Kündigungsandrohung. Vorher zeigte «PDF» in der Mahnliste für jede
    # Stufe — auch die erste — die Kündigungsandrohung.
    rid, stufe_roh = request.GET.get('rechnung'), request.GET.get('stufe')
    if rid and stufe_roh:
        from finance.models import DebitorenRechnung
        from core.services.mahnbrief import forderungs_monat, mahnbrief_pdf
        from core.services.mahnstufen import eigentuemer_von_rechnung, mahnstufen_config
        rechnung = get_object_or_404(DebitorenRechnung, pk=rid, vertrag=vertrag)
        # Nur Stufen, die die Verwaltung eingerichtet hat (crm.MahnStufe); sonst die erste.
        stufen = sorted(mahnstufen_config(eigentuemer_von_rechnung(rechnung),
                                          rechnung.organisation), key=lambda x: x['stufe'])
        try:
            stufe = int(stufe_roh)
        except ValueError:
            stufe = None
        cfg = next((x for x in stufen if x['stufe'] == stufe), None) or (stufen[0] if stufen else None)
        stufe = cfg['stufe'] if cfg else 1
        pdf_bytes = mahnbrief_pdf(
            vertrag, verwaltung, stufe=stufe, monat=forderungs_monat(rechnung),
            betrag=f"{rechnung.offener_betrag:.2f}", datum=heute,
            gebuehr=cfg['gebuehr'] if cfg else None,
            letzte_stufe=bool(cfg and cfg['kuendigung']), rechnung=rechnung)
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = (
            f'inline; filename="Mahnung_{stufe}_{vertrag.mieter.nachname}.pdf"')
        response.write(pdf_bytes)
        return response

    pdf_bytes = generate_mahnung_combined_pdf_bytes(vertrag, verwaltung, monat_str, betrag_str, heute)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Mahnung_Art257d_{vertrag.mieter.nachname}.pdf"'
    response.write(pdf_bytes)
    return response
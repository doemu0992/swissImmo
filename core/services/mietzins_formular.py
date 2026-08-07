"""Amtliches Formular für Mietzinsanpassung (Art. 269d OR, Art. 19 VMWG).

Erzeugt ein rechtlich vollständiges „Mitteilung von Mietzinserhöhungen und
anderen einseitigen Vertragsänderungen"-Formular als PDF (bytes)."""
import logging
import io
import datetime
from decimal import Decimal

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors

logger = logging.getLogger(__name__)



def _fmt(d):
    try:
        return f"{Decimal(str(d)):,.2f}".replace(",", "'")
    except Exception:
        return str(d)


def _wrap(text, breite=95):
    """Einfacher Zeilenumbruch nach Wortgrenzen."""
    worte = (text or "").split()
    zeilen, akt = [], ""
    for w in worte:
        if len(akt) + len(w) + 1 > breite:
            zeilen.append(akt)
            akt = w
        else:
            akt = (akt + " " + w).strip()
    if akt:
        zeilen.append(akt)
    return zeilen or [""]


def generate_amtliches_formular_pdf(vertrag, daten, verwaltung=None, mandant=None):
    """daten: dict mit alt_netto, neu_netto, nebenkosten, alt_zins, neu_zins,
    alt_lik, neu_lik, zins_pct, lik_pct, kosten_pct, total_pct, wirksam_ab (date),
    begruendung, schlichtungsbehoerde (str), mit_vorbehalt (bool), vorbehalt_text."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    mieter = vertrag.mieter
    einheit = vertrag.einheit
    liegenschaft = einheit.liegenschaft

    absender_name = "Immobilienverwaltung"
    absender_strasse = ""
    absender_ort = ""
    unterschrift_pfad = None
    if mandant:
        absender_name = mandant.firma_oder_name
        absender_strasse = mandant.strasse or ""
        absender_ort = f"{mandant.plz or ''} {mandant.ort or ''}".strip()
        if getattr(mandant, 'unterschrift_bild', None):
            try:
                unterschrift_pfad = mandant.unterschrift_bild.path
            except Exception:
                unterschrift_pfad = None
    elif verwaltung:
        absender_name = verwaltung.firma
        absender_strasse = verwaltung.strasse or ""
        absender_ort = f"{verwaltung.plz or ''} {verwaltung.ort or ''}".strip()

    c.setTitle(f"Mietzinsanpassung {mieter.nachname}")

    # Logo
    if verwaltung and getattr(verwaltung, 'logo', None):
        try:
            c.drawImage(verwaltung.logo.path, 155*mm, 272*mm, width=40*mm, preserveAspectRatio=True, mask='auto')
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)

    # Absender
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20*mm, 280*mm, absender_name)
    c.setFont("Helvetica", 9)
    c.drawString(20*mm, 276*mm, absender_strasse)
    c.drawString(20*mm, 272*mm, absender_ort)

    # Empfänger (Fensterkuvert)
    c.setFont("Helvetica", 11)
    c.drawString(20*mm, 250*mm, f"{mieter.vorname} {mieter.nachname}")
    c.drawString(20*mm, 245*mm, mieter.strasse or "")
    c.drawString(20*mm, 240*mm, f"{mieter.plz or ''} {mieter.ort or ''}".strip())

    # Ort/Datum
    heute = datetime.date.today()
    ort_kopf = (absender_ort.split(' ', 1)[-1] if absender_ort else liegenschaft.ort) or ""
    c.drawRightString(190*mm, 240*mm, f"{ort_kopf}, {heute.strftime('%d.%m.%Y')}")

    # Titel
    c.setFont("Helvetica-Bold", 13)
    c.drawString(20*mm, 222*mm, "Mitteilung einer Mietzinsanpassung")
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    c.drawString(20*mm, 217*mm, "Amtliches Formular gemäss Art. 269d OR / Art. 19 VMWG")
    c.setFillColor(colors.black)

    # Objekt
    c.setFont("Helvetica", 10)
    c.drawString(20*mm, 208*mm, f"Mietobjekt: {einheit.bezeichnung}, {liegenschaft.strasse}, {liegenschaft.plz} {liegenschaft.ort}")
    wirksam = daten['wirksam_ab']
    wtxt = wirksam.strftime('%d.%m.%Y') if hasattr(wirksam, 'strftime') else str(wirksam)
    c.drawString(20*mm, 203*mm, f"Wirksam ab: {wtxt}")

    # --- Gegenüberstellung bisher/neu ---
    y = 190*mm
    c.setFillColor(colors.HexColor("#EEF0F5"))
    c.rect(18*mm, y - 30*mm, 174*mm, 34*mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(24*mm, y, "Position")
    c.drawRightString(130*mm, y, "bisher (CHF)")
    c.drawRightString(186*mm, y, "neu (CHF)")
    c.setLineWidth(0.4)
    c.line(24*mm, y - 2*mm, 186*mm, y - 2*mm)

    alt_netto = Decimal(str(daten['alt_netto']))
    neu_netto = Decimal(str(daten['neu_netto']))
    nk = Decimal(str(daten.get('nebenkosten') or 0))

    c.setFont("Helvetica", 10)
    yy = y - 8*mm
    c.drawString(24*mm, yy, "Nettomietzins")
    c.drawRightString(130*mm, yy, _fmt(alt_netto))
    c.drawRightString(186*mm, yy, _fmt(neu_netto))
    yy -= 6*mm
    c.drawString(24*mm, yy, "Nebenkosten (Akonto/Pauschale)")
    c.drawRightString(130*mm, yy, _fmt(nk))
    c.drawRightString(186*mm, yy, _fmt(nk))
    yy -= 3*mm
    c.line(24*mm, yy, 186*mm, yy)
    yy -= 6*mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(24*mm, yy, "Bruttomietzins (total)")
    c.drawRightString(130*mm, yy, _fmt(alt_netto + nk))
    c.drawRightString(186*mm, yy, _fmt(neu_netto + nk))

    diff = neu_netto - alt_netto
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#B91C1C") if diff > 0 else colors.HexColor("#047857"))
    c.drawString(24*mm, yy - 7*mm, f"Veränderung Nettomietzins: {'+' if diff >= 0 else ''}{_fmt(diff)} CHF"
                                   + (f"  ({daten.get('total_pct')} %)" if daten.get('total_pct') is not None else ""))
    c.setFillColor(colors.black)

    # --- Begründung mit Bezifferung ---
    y = 145*mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20*mm, y, "Begründung der Anpassung")
    c.setFont("Helvetica", 9)
    y -= 6*mm
    gruende = []
    if daten.get('alt_zins') is not None and daten.get('neu_zins') is not None and daten['alt_zins'] != daten['neu_zins']:
        gruende.append(f"Referenzzinssatz: {daten['alt_zins']} % → {daten['neu_zins']} %"
                       + (f"  (Anteil {daten.get('zins_pct')} %)" if daten.get('zins_pct') is not None else ""))
    if daten.get('alt_lik') is not None and daten.get('neu_lik') is not None and daten['alt_lik'] != daten['neu_lik']:
        from core.services.lik import stand_label
        _basis = daten.get('lik_basis') or 'Dezember 2020'
        _as = stand_label(daten.get('alt_lik_stand')); _ns = stand_label(daten.get('neu_lik_stand'))
        gruende.append(f"Teuerung (LIK, Basis {_basis} = 100): {daten['alt_lik']} Punkte"
                       + (f" (Stand {_as})" if _as else "") + f" → {daten['neu_lik']} Punkte"
                       + (f" (Stand {_ns})" if _ns else "") + ", 40 % anrechenbar"
                       + (f"  (Anteil {daten.get('lik_pct')} %)" if daten.get('lik_pct') is not None else ""))
    if daten.get('kosten_pct'):
        gruende.append(f"Allgemeine Kostensteigerung: Anteil {daten.get('kosten_pct')} %")
    if daten.get('begruendung'):
        gruende.append(daten['begruendung'])
    if not gruende:
        gruende = ["Anpassung an die aktuellen Grundlagen (Referenzzinssatz und Teuerung)."]
    for g in gruende:
        for zeile in _wrap(f"• {g}", 100):
            c.drawString(22*mm, y, zeile)
            y -= 5*mm

    # --- Vorbehalt ---
    if daten.get('mit_vorbehalt'):
        y -= 2*mm
        c.setFont("Helvetica-Bold", 9)
        c.drawString(20*mm, y, "Vorbehalt:")
        c.setFont("Helvetica", 9)
        y -= 5*mm
        for zeile in _wrap(daten.get('vorbehalt_text') or
                           "Weitere Erhöhungsgründe bleiben vorbehalten (nicht ausgeschöpfte Reserven).", 100):
            c.drawString(22*mm, y, zeile)
            y -= 5*mm

    # --- Rechtsmittelbelehrung (Pflicht) ---
    y = 78*mm
    c.setFillColor(colors.HexColor("#FEF3C7"))
    c.rect(18*mm, y - 20*mm, 174*mm, 26*mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(22*mm, y, "Anfechtung / Rechtsmittelbelehrung")
    c.setFont("Helvetica", 8.5)
    y -= 5*mm
    schlicht = daten.get('schlichtungsbehoerde') or "der zuständigen Schlichtungsbehörde am Ort der Liegenschaft"
    text = (f"Diese Mietzinsanpassung kann innert 30 Tagen nach Empfang bei {schlicht} als missbräuchlich "
            f"angefochten werden (Art. 270b OR). Die Anpassung ist nur gültig, wenn sie mit diesem amtlich "
            f"genehmigten Formular und begründet mitgeteilt wird und die Ankündigungsfrist gewahrt ist.")
    for zeile in _wrap(text, 108):
        c.drawString(22*mm, y, zeile)
        y -= 4.5*mm

    # --- Unterschrift ---
    y = 42*mm
    c.setFont("Helvetica", 10)
    c.drawString(20*mm, y, "Freundliche Grüsse")
    if unterschrift_pfad:
        try:
            c.drawImage(unterschrift_pfad, 20*mm, y - 22*mm, width=48*mm, preserveAspectRatio=True, mask='auto')
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20*mm, 14*mm, absender_name)
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    c.drawString(20*mm, 10*mm, "Vermieter / bevollmächtigte Vertretung")
    c.setFillColor(colors.black)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()

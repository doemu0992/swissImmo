"""Schlussabrechnung beim Auszug eines Mieters.

Fasst offene Mietforderungen, Nebenkosten-Saldo, Schäden/Abzüge und die Kaution
zu einer Endabrechnung zusammen und weist den Saldo (Nachzahlung durch bzw.
Rückzahlung an den Mieter) aus. Erzeugt das PDF."""
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


def berechne_schlussabrechnung(vertrag, auszug_datum, positionen, kaution_verrechnen=True):
    """positionen: Liste von dicts {'text': str, 'betrag': Decimal, 'zulasten': bool,
    'steuerbar': bool}.
    zulasten=True → Mieter schuldet; False → Gutschrift an Mieter.
    steuerbar=True → die Position ist ein Entgelt und bei optierten Verhältnissen
    MWST-pflichtig (typisch: der Nebenkosten-Abrechnungssaldo). Schadenersatz ist
    nach Art. 18 Abs. 2 MWSTG KEIN Entgelt und bleibt steuerfrei — deshalb wird
    pro Position entschieden statt pauschal.
    Gibt dict mit Zeilen + Saldo zurück."""
    from finance.models import DebitorenRechnung
    zeilen = []

    # 1. Offene Mietforderungen (automatisch)
    offene = (DebitorenRechnung.objects.filter(vertrag=vertrag, status__in=['offen', 'teilbezahlt']))
    offen_total = sum((r.offener_betrag for r in offene), Decimal('0.00'))
    if offen_total > 0:
        # Bereits fakturiert (inkl. eigener MWST-Abgrenzung) → nicht nochmals besteuern.
        zeilen.append({'text': 'Offene Mietforderungen', 'betrag': offen_total,
                       'zulasten': True, 'steuerbar': False})

    # 2. Manuelle Positionen (NK-Saldo, Schäden, Reinigung, Gutschriften …)
    for p in positionen:
        b = p.get('betrag') or Decimal('0.00')
        if b == 0:
            continue
        zeilen.append({'text': p.get('text', 'Position'), 'betrag': b,
                       'zulasten': bool(p.get('zulasten', True)),
                       'steuerbar': bool(p.get('steuerbar', False))})

    # Zwischensaldo (ohne Kaution): positiv = Mieter schuldet
    zwischen = Decimal('0.00')
    # Steuerbarer Teilsaldo der NEUEN Positionen — Basis der MWST-Abgrenzung.
    steuerbar_saldo = Decimal('0.00')
    for z in zeilen:
        vorzeichen = Decimal('1') if z['zulasten'] else Decimal('-1')
        zwischen += z['betrag'] * vorzeichen
        if z.get('steuerbar'):
            steuerbar_saldo += z['betrag'] * vorzeichen

    # MWST auf den steuerbaren Anteil (nur bei optiertem Vertrag). Die Beträge
    # werden — wie in der Sollstellung — als NETTO erfasst, die Steuer kommt
    # obendrauf. Ohne diese Abgrenzung fehlte die Steuer in der ESTV-Abrechnung
    # und der Umsatz in Ziffer 289 (Audit).
    satz = (vertrag.mwst_satz or Decimal('0')) if getattr(vertrag, 'mwst_pflichtig', False) else Decimal('0')
    if satz > 0 and steuerbar_saldo != 0:
        mwst_neu = (steuerbar_saldo * satz / Decimal('100')).quantize(Decimal('0.01'))
    else:
        mwst_neu = Decimal('0.00')
    if mwst_neu:
        zeilen.append({'text': f'MWST {satz} % auf steuerbaren Positionen',
                       'betrag': abs(mwst_neu), 'zulasten': mwst_neu > 0, 'steuerbar': False})
        zwischen += mwst_neu

    # 3. Kaution — art-abhängig:
    #    Sperrkonto: Guthaben des Mieters → wird ihm gutgeschrieben (zugunsten).
    #    Versicherung: KEIN Guthaben des Mieters (er zahlte nur Prämien) → wird NICHT
    #    gutgeschrieben; Schäden erscheinen als normale Positionen (zulasten).
    kaution = vertrag.kautions_betrag or Decimal('0.00')
    ist_versicherung = getattr(vertrag, 'ist_kautionsversicherung', False)
    kaution_gutschrift = bool(kaution_verrechnen and kaution > 0 and not ist_versicherung)
    if kaution_gutschrift:
        zeilen.append({'text': 'Mietkaution Sperrkonto (Guthaben Mieter)', 'betrag': kaution, 'zulasten': False})

    saldo = zwischen - (kaution if kaution_gutschrift else Decimal('0.00'))
    # saldo > 0 → Mieter zahlt nach; saldo < 0 → Rückzahlung an Mieter
    return {
        'zeilen': zeilen,
        'offen_total': offen_total,
        'zwischen': zwischen,
        'steuerbar_saldo': steuerbar_saldo,
        'mwst_neu': mwst_neu,
        'mwst_satz': satz,
        'kaution': kaution,
        'ist_versicherung': ist_versicherung,
        'kaution_verrechnen': kaution_gutschrift,
        'saldo': saldo,
        'nachzahlung': saldo > 0,
        'rueckzahlung': -saldo if saldo < 0 else Decimal('0.00'),
        'auszug_datum': auszug_datum,
    }


def generate_schlussabrechnung_pdf(vertrag, daten, verwaltung=None):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    mieter = vertrag.mieter
    einheit = vertrag.einheit
    lg = einheit.liegenschaft
    mandant = lg.mandant if lg else None
    c.setTitle(f"Schlussabrechnung {mieter.nachname}")

    if verwaltung and getattr(verwaltung, 'logo', None):
        try:
            c.drawImage(verwaltung.logo.path, 155*mm, 272*mm, width=40*mm, preserveAspectRatio=True, mask='auto')
        except Exception:
            logger.debug("Fehler bewusst übergangen", exc_info=True)

    absender = mandant.firma_oder_name if mandant else (verwaltung.firma if verwaltung else 'Immobilienverwaltung')
    a_str = (mandant.strasse if mandant else (verwaltung.strasse if verwaltung else '')) or ''
    a_ort = (f"{mandant.plz} {mandant.ort}" if mandant else (f"{verwaltung.plz} {verwaltung.ort}" if verwaltung else '')) or ''
    c.setFont("Helvetica-Bold", 9); c.drawString(20*mm, 280*mm, absender)
    c.setFont("Helvetica", 9); c.drawString(20*mm, 276*mm, a_str); c.drawString(20*mm, 272*mm, a_ort)

    # Empfänger (Auszugsadresse: zum heutigen Stichtag gültige Zustelladresse aus
    # der datierten Adress-Historie — Korrespondenzadresse hat Vorrang, sonst
    # die aktuelle Wohnadresse; Fallback auf die Flat-Felder).
    _zs, _zz, _zplz, _zort = mieter.zustelladresse()
    ziel_strasse = _zs or mieter.strasse or ''
    ziel_ort = f"{_zplz or mieter.plz or ''} {_zort or mieter.ort or ''}".strip()
    c.setFont("Helvetica", 11)
    c.drawString(20*mm, 250*mm, f"{mieter.vorname} {mieter.nachname}")
    c.drawString(20*mm, 245*mm, ziel_strasse)
    c.drawString(20*mm, 240*mm, ziel_ort)

    c.setFont("Helvetica-Bold", 15)
    c.drawString(20*mm, 220*mm, "Schlussabrechnung")
    c.setFont("Helvetica", 9); c.setFillColor(colors.grey)
    az = daten['auszug_datum']
    az_str = az.strftime('%d.%m.%Y') if hasattr(az, 'strftime') else str(az)
    c.drawString(20*mm, 214*mm, f"Mietobjekt: {einheit.bezeichnung}, {lg.strasse}, {lg.plz} {lg.ort}")
    c.drawString(20*mm, 209*mm, f"Auszug per: {az_str}")
    c.setFillColor(colors.black)

    # Tabelle
    y = 196*mm
    c.setFillColor(colors.HexColor("#EEF0F5")); c.rect(18*mm, y-2*mm, 174*mm, 8*mm, fill=1, stroke=0)
    c.setFillColor(colors.black); c.setFont("Helvetica-Bold", 9)
    c.drawString(22*mm, y, "Position")
    c.drawRightString(150*mm, y, "zulasten")
    c.drawRightString(186*mm, y, "zugunsten")
    y -= 9*mm
    c.setFont("Helvetica", 10)
    for z in daten['zeilen']:
        if y < 60*mm:
            c.showPage(); y = 270*mm
        c.drawString(22*mm, y, z['text'][:60])
        if z['zulasten']:
            c.drawRightString(150*mm, y, _fmt(z['betrag']))
        else:
            c.drawRightString(186*mm, y, _fmt(z['betrag']))
        y -= 6*mm

    y -= 2*mm
    c.setLineWidth(0.6); c.line(18*mm, y, 192*mm, y); y -= 8*mm

    saldo = daten['saldo']
    c.setFillColor(colors.HexColor("#FEF2F2") if daten['nachzahlung'] else colors.HexColor("#ECFDF5"))
    c.rect(18*mm, y-6*mm, 174*mm, 16*mm, fill=1, stroke=0)
    c.setFillColor(colors.black); c.setFont("Helvetica-Bold", 12)
    if daten['nachzahlung']:
        c.drawString(22*mm, y, "Nachzahlung durch Mieter")
        c.drawRightString(188*mm, y, f"CHF {_fmt(saldo)}")
    else:
        c.drawString(22*mm, y, "Rückzahlung an Mieter")
        c.drawRightString(188*mm, y, f"CHF {_fmt(daten['rueckzahlung'])}")

    # Hinweis + Zahlungsangaben
    y -= 22*mm
    c.setFont("Helvetica", 9); c.setFillColor(colors.grey)
    if daten['nachzahlung']:
        c.drawString(20*mm, y, "Bitte überweisen Sie den Betrag innert 30 Tagen. Besten Dank.")
    else:
        c.drawString(20*mm, y, "Der Betrag wird auf das uns bekannte / von Ihnen genannte Konto überwiesen.")
        if mieter.iban:
            c.drawString(20*mm, y-5*mm, f"IBAN: {mieter.iban}")
    c.setFillColor(colors.black)

    c.setFont("Helvetica", 10)
    c.drawString(20*mm, 42*mm, "Freundliche Grüsse")
    # Digitale Unterschrift zwischen Gruss und Absendername — der Absender oben
    # ist der Mandant (sonst die Verwaltung), also unterschreibt er auch.
    from core.services.unterschrift import unterschrift_zeichnen
    unterschrift_zeichnen(c, 20*mm, 34*mm, mandant, verwaltung, max_hoehe=7*mm)
    c.setFont("Helvetica-Bold", 10); c.drawString(20*mm, 33*mm, absender)

    # Rechtlicher Hinweis (Rückgabe/Mängelrüge + Kaution)
    c.setFont("Helvetica", 6.5); c.setFillColor(colors.grey)
    c.drawString(20*mm, 16*mm, "Rückgabe der Mietsache: Art. 267 OR; Prüfung und Mängelrüge des Vermieters: Art. 267a OR.")
    c.drawString(20*mm, 13*mm, "Mietzinsdepot / Kaution: Art. 257e OR (Freigabe durch die Bank i.d.R. ein Jahr nach Mietende ohne Betreibung/Klage).")
    c.setFillColor(colors.black)

    c.showPage(); c.save(); buffer.seek(0)
    return buffer.read()

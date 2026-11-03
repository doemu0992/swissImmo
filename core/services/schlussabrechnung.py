"""Schlussabrechnung beim Auszug eines Mieters.

Fasst offene Mietforderungen, Nebenkosten-Saldo, Schäden/Abzüge und die Kaution
zu einer Endabrechnung zusammen und weist den Saldo (Nachzahlung durch bzw.
Rückzahlung an den Mieter) aus. Erzeugt das PDF."""
import logging
import io
import datetime
from decimal import Decimal

from reportlab.lib.units import mm
from reportlab.lib import colors

from core.services.dok_layout import DokCanvas
from core.services.dokumentsprache import nur_deutsch

logger = logging.getLogger(__name__)


def _fmt(d):
    try:
        return f"{Decimal(str(d)):,.2f}".replace(",", "'")
    except Exception:
        return str(d)


def berechne_schlussabrechnung(vertrag, auszug_datum, positionen, kaution_verrechnen=True,
                               kaution_bilanziert=None):
    """positionen: Liste von dicts {'text': str, 'betrag': Decimal, 'zulasten': bool,
    'steuerbar': bool}.

    kaution_bilanziert: die TATSÄCHLICH auf dem Sperrkonto bilanzierte Kaution
    (2010-Saldo, via _kaution_bilanziert). Wird sie übergeben, ist sie die
    Obergrenze der Gutschrift — sonst zeigte die Abrechnung/das PDF dem Mieter das
    volle VEREINBARTE Depot als Guthaben, obwohl die Buchung nur den einbezahlten
    Teil freigibt (nicht voll einbezahlt / teilweise schon aufgelöst). Anzeige und
    Buchung liefen so auseinander (QS-Befund).
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
    satz = vertrag.mwst_satz_wirksam
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
    # Gutschrift höchstens in Höhe der bilanzierten (einbezahlten/noch offenen)
    # Kaution — deckungsgleich mit der Buchung (min(vereinbart, bilanziert)).
    if kaution_bilanziert is not None and not ist_versicherung:
        kaution = min(kaution, max(Decimal('0.00'), kaution_bilanziert))
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


@nur_deutsch
def generate_schlussabrechnung_pdf(vertrag, daten, verwaltung=None):
    buffer = io.BytesIO()
    mieter = vertrag.mieter
    einheit = vertrag.einheit
    lg = einheit.liegenschaft
    eigentuemer = lg.eigentuemer if lg else None

    absender = eigentuemer.firma_oder_name if eigentuemer else (verwaltung.firma if verwaltung else 'Immobilienverwaltung')
    a_str = (eigentuemer.strasse if eigentuemer else (verwaltung.strasse if verwaltung else '')) or ''
    a_ort = (f"{eigentuemer.plz} {eigentuemer.ort}" if eigentuemer else (f"{verwaltung.plz} {verwaltung.ort}" if verwaltung else '')) or ''
    c = DokCanvas(buffer, organisation=verwaltung, absender=[absender, a_str, a_ort],
                  titel="Schlussabrechnung", ref=f"{mieter.display_name} · {einheit.bezeichnung}")
    c.setTitle(f"Schlussabrechnung {mieter.nachname}")

    # Empfänger (Auszugsadresse: zum heutigen Stichtag gültige Zustelladresse aus
    # der datierten Adress-Historie — Korrespondenzadresse hat Vorrang, sonst
    # die aktuelle Wohnadresse; Fallback auf die Flat-Felder).
    _zs, _zz, _zplz, _zort = mieter.zustelladresse()
    ziel_strasse = _zs or mieter.strasse or ''
    ziel_ort = f"{_zplz or mieter.plz or ''} {_zort or mieter.ort or ''}".strip()
    az = daten['auszug_datum']
    az_str = az.strftime('%d.%m.%Y') if hasattr(az, 'strftime') else str(az)
    ort = (getattr(verwaltung, 'ort', '') or '') if verwaltung else ''
    y0 = c.brief([f"{mieter.vorname} {mieter.nachname}", ziel_strasse, ziel_ort],
                 f"{ort + ', ' if ort else ''}{datetime.date.today().strftime('%d.%m.%Y')}", "Schlussabrechnung",
                 untertitel=f"Auszug per: {az_str}")
    c.setFont("Helvetica", 9); c.setFillColor(colors.HexColor("#374151"))
    c.drawString(20*mm, y0 + 3*mm, f"Mietobjekt: {einheit.bezeichnung}, {lg.strasse}, {lg.plz} {lg.ort}")
    c.setFillColor(colors.black)

    # Tabelle
    def tabellenkopf(y):
        c.setFillColor(colors.HexColor("#EEF0F5")); c.rect(18*mm, y-2*mm, 174*mm, 8*mm, fill=1, stroke=0)
        c.setFillColor(colors.black); c.setFont("Helvetica-Bold", 9)
        c.drawString(22*mm, y, "Position")
        c.drawRightString(150*mm, y, "zulasten")
        c.drawRightString(186*mm, y, "zugunsten")
        c.setFont("Helvetica", 10)
        return y - 9*mm

    y = tabellenkopf(y0 - 8*mm)
    for z in daten['zeilen']:
        if y < 60*mm:
            c.showPage(); y = tabellenkopf(c.Y_FOLGE)
        c.drawString(22*mm, y, z['text'][:60])
        if z['zulasten']:
            c.drawRightString(150*mm, y, _fmt(z['betrag']))
        else:
            c.drawRightString(186*mm, y, _fmt(z['betrag']))
        y -= 6*mm

    # Ab hier ein zusammenhängender Block (Saldo, Hinweise, Gruss, Unterschrift, Rechtshinweis): nie über einen Seitenumbruch
    if y < c.UNTEN + 78*mm:
        c.showPage(); y = c.Y_FOLGE
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

    y -= 14*mm
    c.setFont("Helvetica", 10)
    c.drawString(20*mm, y, "Freundliche Grüsse")
    # Digitale Unterschrift zwischen Gruss und Absendername — der Absender oben
    # ist der Eigentuemer (sonst die Verwaltung), also unterschreibt er auch.
    from core.services.unterschrift import unterschrift_zeichnen
    unterschrift_zeichnen(c, 20*mm, y - 8*mm, eigentuemer, verwaltung, max_hoehe=7*mm)
    c.setFont("Helvetica-Bold", 10); c.drawString(20*mm, y - 9*mm, absender)

    # Rechtlicher Hinweis (Rückgabe/Mängelrüge + Kaution)
    y -= 19*mm
    c.setFont("Helvetica", 6.5); c.setFillColor(colors.HexColor("#4b5563"))
    c.drawString(20*mm, y, "Rückgabe der Mietsache: Art. 267 OR; Prüfung und Mängelrüge des Vermieters: Art. 267a OR.")
    c.drawString(20*mm, y - 3*mm, "Mietzinsdepot / Kaution: Art. 257e OR (Freigabe durch die Bank i.d.R. ein Jahr nach Mietende ohne Betreibung/Klage).")
    c.setFillColor(colors.black)

    c.showPage(); c.save(); buffer.seek(0)
    return buffer.read()

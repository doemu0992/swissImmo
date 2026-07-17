"""Zusätzliche mietrechtliche Briefe/Belege als PDF (reportlab):

- Kautions-Hinterlegungsbestätigung an die Mieterschaft (Art. 257e OR)
- Kautions-Freigabeschreiben an die Bank (Sperrkonto-Freigabe)
- Mängelrüge / Fristansetzung zur Mängelbeseitigung (Art. 259a–259g OR)

Bewusst schlank gehalten (einfache Geschäftsbriefe), analog zum Serienbrief.
"""
import io
import datetime
from decimal import Decimal

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def _absender_zeilen(verwaltung, mandant):
    if mandant:
        return [mandant.firma_oder_name, mandant.strasse or '',
                f"{mandant.plz or ''} {mandant.ort or ''}".strip()]
    if verwaltung:
        return [verwaltung.firma or '', verwaltung.strasse or '',
                f"{verwaltung.plz or ''} {verwaltung.ort or ''}".strip()]
    return ['Immobilienverwaltung', '', '']


def _fr(d):
    try:
        return f"{Decimal(str(d)):,.2f}".replace(',', "'")
    except Exception:
        return '0.00'


def _wrap(text, breite):
    zeilen, akt = [], ''
    for wort in (text or '').split():
        if len(akt) + len(wort) + 1 > breite:
            zeilen.append(akt); akt = wort
        else:
            akt = (akt + ' ' + wort).strip()
    if akt:
        zeilen.append(akt)
    return zeilen or ['']


def _brief(absender, empfaenger_zeilen, ort, betreff, absaetze, gruss_name):
    """Rendert einen einfachen A4-Geschäftsbrief und gibt die PDF-Bytes zurück."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    heute = datetime.date.today().strftime('%d.%m.%Y')
    # Absender
    c.setFont("Helvetica", 8)
    c.drawString(25 * mm, 280 * mm, ' · '.join(z for z in absender if z))
    # Empfänger
    c.setFont("Helvetica", 11)
    y = 255 * mm
    for z in empfaenger_zeilen:
        c.drawString(120 * mm, y, z); y -= 5.2 * mm
    # Ort/Datum
    c.setFont("Helvetica", 10)
    c.drawString(120 * mm, y - 6 * mm, f"{ort}, {heute}")
    # Betreff
    c.setFont("Helvetica-Bold", 11)
    c.drawString(25 * mm, 225 * mm, betreff)
    # Text
    c.setFont("Helvetica", 10.5)
    ty = 213 * mm
    for absatz in absaetze:
        for zeile in _wrap(absatz, 92):
            c.drawString(25 * mm, ty, zeile); ty -= 5.4 * mm
        ty -= 3.5 * mm
        if ty < 45 * mm:
            c.showPage(); c.setFont("Helvetica", 10.5); ty = 270 * mm
    # Grussformel
    ty -= 4 * mm
    c.drawString(25 * mm, ty, "Freundliche Grüsse")
    c.drawString(25 * mm, ty - 16 * mm, gruss_name)
    c.showPage(); c.save(); buf.seek(0)
    return buf.read()


def _kontext(vertrag, verwaltung=None):
    from crm.models import Verwaltung
    mieter = vertrag.mieter
    einheit = vertrag.einheit
    lg = einheit.liegenschaft if einheit else None
    mandant = lg.mandant if lg else None
    vw = verwaltung or (lg.verwaltung if lg else None) or Verwaltung.objects.first()
    absender = _absender_zeilen(vw, mandant)
    ort = absender[2].split(' ', 1)[-1] if absender[2] else (lg.ort if lg else '')
    empf = [mieter.display_name]
    zustell = mieter.zustelladresse() if hasattr(mieter, 'zustelladresse') else (mieter.strasse, '', mieter.plz, mieter.ort)
    s, _zus, plz, o = zustell
    if s:
        empf.append(s)
    if (plz or o):
        empf.append(f"{plz or ''} {o or ''}".strip())
    objekt = f"{einheit.bezeichnung}, {lg.strasse}, {lg.plz} {lg.ort}" if einheit and lg else ''
    return mieter, einheit, lg, absender, ort, empf, objekt, absender[0]


def kaution_hinterlegung_pdf(vertrag, verwaltung=None):
    """Bestätigung der Kautionshinterlegung an die Mieterschaft (Art. 257e OR)."""
    mieter, einheit, lg, absender, ort, empf, objekt, name = _kontext(vertrag, verwaltung)
    betrag = _fr(vertrag.kautions_betrag or 0)
    if getattr(vertrag, 'ist_kautionsversicherung', False):
        depot = (f"Die Sicherheit wurde als Kautionsversicherung bei "
                 f"{vertrag.kautions_versicherer or 'der Versicherung'} "
                 f"(Police {vertrag.kautions_policennummer or '—'}) hinterlegt.")
    else:
        depot = (f"Die Sicherheit wurde auf ein auf Ihren Namen lautendes Sperrkonto "
                 f"{('bei ' + vertrag.kautions_konto) if vertrag.kautions_konto else 'bei der Bank'} "
                 f"einbezahlt. Das Konto lautet auf Ihren Namen; Auszahlungen erfolgen nur mit "
                 f"Ihrer Zustimmung oder aufgrund eines rechtskräftigen Entscheids.")
    eingezahlt = vertrag.kautions_einbezahlt_am.strftime('%d.%m.%Y') if vertrag.kautions_einbezahlt_am else '—'
    absaetze = [
        f"Sehr geehrte Damen und Herren",
        f"Für das Mietobjekt {objekt} bestätigen wir den Eingang der Mietkaution von "
        f"CHF {betrag} (Eingang am {eingezahlt}).",
        depot,
        "Die Kaution dient der Sicherung allfälliger Ansprüche aus dem Mietverhältnis. Sie wird "
        "nach dessen Beendigung und ordnungsgemässer Rückgabe des Mietobjekts freigegeben. Macht die "
        "Vermieterschaft nicht innert eines Jahres nach Beendigung des Mietverhältnisses rechtlich "
        "Ansprüche geltend, so kann die Mieterschaft die Rückerstattung von der Bank verlangen "
        "(Art. 257e Abs. 3 OR).",
    ]
    return _brief(absender, empf, ort, f"Bestätigung Mietkaution — {objekt}", absaetze, name)


def kaution_freigabe_pdf(vertrag, verwaltung=None):
    """Freigabe-/Auszahlungsauftrag an die Bank (Sperrkonto-Freigabe)."""
    mieter, einheit, lg, absender, ort, _empf, objekt, name = _kontext(vertrag, verwaltung)
    betrag = _fr(vertrag.kautions_betrag or 0)
    ausz = vertrag.kautions_rueckzahlung_betrag
    abzug = vertrag.kautions_abzug_betrag
    bank_empf = [vertrag.kautions_konto or 'Depotbank', '', '']
    absaetze = [
        "Sehr geehrte Damen und Herren",
        f"Für das per {vertrag.ende.strftime('%d.%m.%Y') if vertrag.ende else '—'} beendete "
        f"Mietverhältnis mit {mieter.display_name} (Mietobjekt {objekt}) geben wir das "
        f"Mietzinsdepot von CHF {betrag} frei.",
    ]
    if ausz is not None or abzug is not None:
        teile = []
        if ausz is not None:
            teile.append(f"Auszahlung an die Mieterschaft: CHF {_fr(ausz)}")
        if abzug is not None and abzug > 0:
            teile.append(f"Einbehalt zugunsten der Vermieterschaft: CHF {_fr(abzug)}"
                         + (f" ({vertrag.kautions_abzug_grund})" if vertrag.kautions_abzug_grund else ""))
        absaetze.append("Wir bitten Sie um folgende Verteilung: " + '; '.join(teile) + ".")
    else:
        absaetze.append("Wir bitten Sie, das Depot vollumfänglich gemäss beiliegender Vereinbarung "
                        "bzw. mit Zustimmung der Mieterschaft freizugeben.")
    absaetze.append("Bitte bestätigen Sie uns die Ausführung. Besten Dank für Ihre Bemühungen.")
    return _brief(absender, bank_empf, ort, f"Freigabe Mietzinsdepot — {mieter.display_name}", absaetze, name)


def maengelruege_pdf(vertrag, mangel_text, frist_tage=14, verwaltung=None):
    """Mängelrüge / Fristansetzung zur Mängelbeseitigung (Art. 259a–259g OR).
    Kann sowohl als Aufforderung an die Mieterschaft (Schäden) wie als Beleg
    verwendet werden; Standard: Aufforderung zur Behebung innert Frist."""
    mieter, einheit, lg, absender, ort, empf, objekt, name = _kontext(vertrag, verwaltung)
    frist_datum = (datetime.date.today() + datetime.timedelta(days=int(frist_tage))).strftime('%d.%m.%Y')
    absaetze = [
        "Sehr geehrte Damen und Herren",
        f"Am Mietobjekt {objekt} wurde folgender Mangel festgestellt bzw. gemeldet:",
        mangel_text or "—",
        f"Wir setzen Ihnen hiermit eine Frist bis zum {frist_datum} zur Behebung des Mangels "
        f"an. Wird der Mangel innert dieser Frist nicht behoben, behalten wir uns die gesetzlich "
        f"vorgesehenen Rechtsbehelfe vor (Art. 259a–259i OR: Mängelbeseitigung, Herabsetzung des "
        f"Mietzinses, Schadenersatz, Hinterlegung des Mietzinses bei der Schlichtungsbehörde).",
        "Für Rückfragen stehen wir Ihnen gerne zur Verfügung.",
    ]
    return _brief(absender, empf, ort, f"Mängelrüge / Fristansetzung — {objekt}", absaetze, name)


def untermiete_zustimmung_pdf(vertrag, untermieter, entscheid='zustimmung',
                              bedingungen='', verwaltung=None):
    """Zustimmung oder Ablehnung zur Untervermietung (Art. 262 OR).
    entscheid: 'zustimmung' | 'ablehnung'."""
    mieter, einheit, lg, absender, ort, empf, objekt, name = _kontext(vertrag, verwaltung)
    if entscheid == 'ablehnung':
        betreff = f"Untervermietung — Ablehnung ({objekt})"
        absaetze = [
            "Sehr geehrte Damen und Herren",
            f"Sie haben um Zustimmung zur Untervermietung des Mietobjekts {objekt} an "
            f"{untermieter or 'die genannte Person'} ersucht.",
            "Wir können der Untervermietung leider nicht zustimmen. Die Ablehnung stützt sich auf "
            "Art. 262 Abs. 2 OR (z.B. missbräuchliche Bedingungen der Untermiete, wesentliche "
            "Nachteile für die Vermieterschaft oder Verweigerung der Bekanntgabe der Bedingungen).",
            (bedingungen or "").strip() or "Für Rückfragen stehen wir Ihnen gerne zur Verfügung.",
        ]
    else:
        betreff = f"Untervermietung — Zustimmung ({objekt})"
        absaetze = [
            "Sehr geehrte Damen und Herren",
            f"Wir bestätigen Ihnen unsere Zustimmung zur Untervermietung des Mietobjekts {objekt} "
            f"an {untermieter or 'die genannte Person'} gemäss Art. 262 OR.",
            "Die Zustimmung erfolgt unter folgenden Bedingungen: " + (
                (bedingungen or "").strip() or
                "Die Hauptmieterschaft bleibt für sämtliche Pflichten aus dem Hauptmietvertrag "
                "verantwortlich (insb. Mietzins, Sorgfalt, Rückgabe). Der Untermietzins darf nicht "
                "missbräuchlich sein."),
            "Diese Zustimmung entbindet die Hauptmieterschaft nicht von ihren Verpflichtungen "
            "gegenüber der Vermieterschaft.",
        ]
    return _brief(absender, empf, ort, betreff, absaetze, name)


def rueckgabe_maengelruege_pdf(vertrag, maengel, verwaltung=None, abnahme_datum=None):
    """Sofortige Mängelrüge nach Rückgabe des Mietobjekts (Art. 267a OR).

    Muss dem ausgezogenen Mieter SOFORT nach der Abnahme zugehen (Praxis:
    2-3 Arbeitstage), sonst sind die Ersatzansprüche der Vermieterschaft
    verwirkt (Abs. 1-2). Versteckte, bei übungsgemässer Untersuchung nicht
    erkennbare Mängel bleiben vorbehalten (Abs. 3).

    `maengel`: Liste von dicts {'raum', 'beschreibung', 'betrag' (optional)}
    oder von Strings."""
    mieter, einheit, lg, absender, ort, empf, objekt, name = _kontext(vertrag, verwaltung)
    datum_txt = (abnahme_datum.strftime('%d.%m.%Y') if abnahme_datum
                 else (vertrag.ende.strftime('%d.%m.%Y') if vertrag.ende else '—'))
    zeilen = []
    total = Decimal('0.00')
    for m in maengel:
        if isinstance(m, str):
            zeilen.append(f"– {m}")
            continue
        teil = f"– {m.get('raum') + ': ' if m.get('raum') else ''}{m.get('beschreibung', '')}"
        if m.get('betrag'):
            teil += f" (Kostenanteil ca. CHF {_fr(m['betrag'])})"
            try:
                total += Decimal(str(m['betrag']))
            except Exception:
                pass
        zeilen.append(teil)
    absaetze = [
        "Sehr geehrte Damen und Herren",
        f"Anlässlich der Rückgabe des Mietobjekts {objekt} am {datum_txt} haben wir "
        "bei der Prüfung folgende Mängel festgestellt, für die Sie nach unserer "
        "Auffassung einzustehen haben (Art. 267a OR):",
        "\n".join(zeilen),
    ]
    if total > 0:
        absaetze.append(f"Der voraussichtliche, von Ihnen zu tragende Kostenanteil beträgt "
                        f"gesamthaft ca. CHF {_fr(total)} (Detail gemäss Abnahmeprotokoll; "
                        f"massgeblich sind die effektiven Instandstellungskosten unter "
                        f"Berücksichtigung der Lebensdauer, «neu für alt»).")
    absaetze += [
        "Wir behalten uns ausdrücklich die Geltendmachung von Mängeln vor, die bei der "
        "übungsgemässen Untersuchung nicht erkennbar waren (versteckte Mängel, "
        "Art. 267a Abs. 3 OR).",
        "Die detaillierte Abrechnung folgt mit der Schlussabrechnung; ein allfälliger "
        "Anteil wird mit dem Mietzinsdepot verrechnet.",
    ]
    return _brief(absender, empf, ort,
                  f"Mängelrüge nach Rückgabe (Art. 267a OR) — {objekt}", absaetze, name)

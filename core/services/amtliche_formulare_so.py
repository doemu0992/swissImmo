"""Amtliche Formulare Kanton Solothurn (auto-befüllt):
- Mitteilung von Mietzins- und anderen Mietvertragsänderungen (Art. 269d OR)
- Kündigung von Wohn- und Geschäftsräumen (Art. 266l/298 OR, Art. 9 VMWG)

Originalgetreue Nachbildung (Seite 1 = Datenfelder, Seite 2 = Rechtsmittel-
belehrung + Schlichtungsbehörden SO). Die mechanisch nachgebildete Unterschrift
ist bei diesen Formularen zulässig (Art. 269d Abs. 4 OR)."""
import io
from decimal import Decimal

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors

SCHLICHTUNGSBEHOERDEN_SO = [
    ("Amtei Solothurn-Lebern", "Schlichtungsbehörde für Miete und Pacht Solothurn-Lebern, Rötistrasse 4, 4501 Solothurn", "Tel. 032 627 75 27"),
    ("Amtei Bucheggberg-Wasseramt", "Schlichtungsbehörde für Miete und Pacht Bucheggberg-Wasseramt, Rötistrasse 4, 4501 Solothurn", "Tel. 032 627 75 27"),
    ("Amtei Thal-Gäu", "Schlichtungsbehörde für Miete und Pacht Thal-Gäu, Amthaus, Amthausquai 23, 4601 Olten", "Tel. 062 311 91 61"),
    ("Amtei Olten-Gösgen", "Schlichtungsbehörde für Miete und Pacht Olten-Gösgen, Amthaus, Amthausquai 23, 4601 Olten", "Tel. 062 311 86 44"),
    ("Amtei Dorneck-Thierstein", "Schlichtungsbehörde für Miete und Pacht Dorneck-Thierstein, Amthaus, Amthausquai 23, 4601 Olten", "Tel. 061 785 77 20"),
]


def _fr(d):
    try:
        return f"{Decimal(str(d)):,.2f}".replace(",", "'")
    except Exception:
        return ""


def _absender(verwaltung, mandant):
    if mandant:
        return [mandant.firma_oder_name, mandant.strasse or "", f"{mandant.plz or ''} {mandant.ort or ''}".strip()]
    if verwaltung:
        return [verwaltung.firma or "", verwaltung.strasse or "", f"{verwaltung.plz or ''} {verwaltung.ort or ''}".strip()]
    return ["Immobilienverwaltung", "", ""]


def _kopf(c, titel_klein, kanton_name="Solothurn"):
    c.setFont("Helvetica-Oblique", 7.5)
    c.setFillColor(colors.black)
    c.drawString(20*mm, 288*mm, titel_klein)
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(190*mm, 287*mm, f"KANTON {kanton_name.lower()}")


def _feldlinie(c, x, y, breite):
    c.setStrokeColor(colors.HexColor("#B8BEC9"))
    c.setLineWidth(0.5)
    c.line(x, y, x + breite, y)


def _schlichtung_seite(c, titel, kanton_name="Solothurn", behoerden=None, exakt=True):
    """Seite 2: Rechtsmittelbelehrung + Schlichtungsbehörden des Kantons."""
    behoerden = behoerden if behoerden is not None else SCHLICHTUNGSBEHOERDEN_SO
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20*mm, 280*mm, "Rechtsmittelbelehrung")
    c.setFont("Helvetica", 8.5)
    y = 273*mm
    for zeile in titel:
        c.drawString(20*mm, y, zeile)
        y -= 4.5*mm
    y -= 4*mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20*mm, y, f"Schlichtungsbehörden im Kanton {kanton_name}" if kanton_name else "Zuständige Schlichtungsbehörde")
    y -= 7*mm
    for amtei, adr, tel in behoerden:
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(20*mm, y, amtei)
        c.setFont("Helvetica", 8)
        c.drawString(20*mm, y - 4*mm, adr)
        c.drawString(20*mm, y - 8*mm, tel)
        y -= 13*mm
    if not exakt:
        c.setFont("Helvetica-Oblique", 8)
        c.setFillColor(colors.HexColor("#B45309"))
        c.drawString(20*mm, y, "Hinweis: Für diesen Kanton ist die genaue Schlichtungsbehörden-Adresse noch zu hinterlegen —")
        c.drawString(20*mm, y - 4*mm, "vor Versand bitte die amtliche Adresse ergänzen.")
        c.setFillColor(colors.black)
    c.setFont("Helvetica-Oblique", 7.5)
    c.setFillColor(colors.grey)
    c.drawString(20*mm, 14*mm, "Auszüge aus OR / VMWG gemäss amtlichem Formular. Gesetzestexte: www.fedlex.admin.ch")
    c.setFillColor(colors.black)


# ============================================================
# 1) MIETZINSANPASSUNG (Art. 269d OR)
# ============================================================
def mietzins_so_pdf(vertrag, daten, verwaltung=None):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    mieter = vertrag.mieter
    einheit = vertrag.einheit
    lg = einheit.liegenschaft
    mandant = lg.mandant if lg else None
    c.setTitle(f"Mietzinsanpassung {mieter.nachname}")

    from core.services.kantone import schlichtung_block
    _kt, kanton_name, behoerden, exakt = schlichtung_block(lg)
    _kopf(c, "Amtliches Formular zur Mitteilung von Mietzins- und anderen Mietvertragsänderungen",
          kanton_name=kanton_name or "Solothurn")

    # Absender / Adressat
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20*mm, 275*mm, "Absender:")
    c.drawString(110*mm, 275*mm, "Adressat:")
    c.setFont("Helvetica-Bold", 8)
    c.drawString(110*mm, 270*mm, "Einschreiben R")
    c.setFont("Helvetica", 9)
    yy = 270*mm
    for line in _absender(verwaltung, mandant):
        c.drawString(20*mm, yy, line); yy -= 4.5*mm
    c.drawString(110*mm, 265*mm, f"{mieter.vorname} {mieter.nachname}")
    c.drawString(110*mm, 260.5*mm, mieter.strasse or "")
    c.drawString(110*mm, 256*mm, f"{mieter.plz or ''} {mieter.ort or ''}".strip())

    # Nachtrag / Mietvertrag / Objekt
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20*mm, 246*mm, "Nachtrag-Nr:")
    c.drawString(110*mm, 246*mm, "zum Mietvertrag vom:")
    c.setFont("Helvetica", 9)
    c.drawString(150*mm, 246*mm, vertrag.beginn.strftime('%d.%m.%Y') if vertrag.beginn else "")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20*mm, 240*mm, "Mietobjekt:")
    c.setFont("Helvetica", 9)
    c.drawString(45*mm, 240*mm, f"{einheit.bezeichnung}, {lg.strasse}, {lg.plz} {lg.ort}")

    c.setFont("Helvetica-Bold", 15)
    c.drawString(20*mm, 230*mm, "Mitteilung von Vertragsänderungen")

    # A) Tabelle
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20*mm, 220*mm, "A) Mietzins, Heiz- und Betriebskosten")
    c.setFont("Helvetica", 8)
    c.drawString(110*mm, 220*mm, "pro Monat")
    c.setFont("Helvetica-Bold", 8)
    c.drawString(110*mm, 215*mm, "bisher")
    wtxt = daten['wirksam_ab'].strftime('%d.%m.%Y') if hasattr(daten['wirksam_ab'], 'strftime') else str(daten['wirksam_ab'])
    c.drawString(150*mm, 215*mm, f"neu ab: {wtxt}")

    alt_netto = Decimal(str(daten['alt_netto']))
    neu_netto = Decimal(str(daten['neu_netto']))
    nk = Decimal(str(daten.get('nebenkosten') or 0))
    y = 208*mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20*mm, y, "Nettomietzins")
    c.setFont("Helvetica", 9)
    c.drawString(110*mm, y, f"Fr. {_fr(alt_netto)}")
    c.drawString(150*mm, y, f"Fr. {_fr(neu_netto)}")
    y -= 6*mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20*mm, y, "Neben- und Betriebskosten")
    c.setFont("Helvetica", 9)
    c.drawString(110*mm, y, f"Fr. {_fr(nk)}")
    c.drawString(150*mm, y, f"Fr. {_fr(nk)}")
    y -= 8*mm
    c.setLineWidth(0.6); c.line(20*mm, y + 3*mm, 190*mm, y + 3*mm)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20*mm, y, "Bruttomietzins:")
    c.drawString(110*mm, y, f"Fr. {_fr(alt_netto + nk)}")
    c.drawString(150*mm, y, f"Fr. {_fr(neu_netto + nk)}")

    # C) Begründung
    y -= 12*mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20*mm, y, "C) Begründung der Änderungen")
    c.setFont("Helvetica", 9)
    gruende = []
    if daten.get('alt_zins') is not None and daten.get('neu_zins') is not None and daten['alt_zins'] != daten['neu_zins']:
        gruende.append(f"Anpassung an den Referenzzinssatz: {daten['alt_zins']} % → {daten['neu_zins']} %.")
    if daten.get('alt_lik') is not None and daten.get('neu_lik') is not None and daten['alt_lik'] != daten['neu_lik']:
        gruende.append(f"Teuerungsausgleich (LIK): {daten['alt_lik']} → {daten['neu_lik']} Punkte, 40 % anrechenbar.")
    if daten.get('kosten_pct'):
        gruende.append(f"Allgemeine Kostensteigerung: {daten.get('kosten_pct')} %.")
    if daten.get('begruendung'):
        gruende.append(daten['begruendung'])
    if not gruende:
        gruende = ["Anpassung an die aktuellen Grundlagen (Referenzzinssatz und Teuerung)."]
    y -= 6*mm
    for g in gruende:
        for zeile in _wrap(g, 105):
            c.drawString(22*mm, y, zeile); y -= 5*mm

    # D) Mehrleistungen
    y -= 3*mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20*mm, y, "D) Erhöhung wegen Mehrleistungen / Förderbeiträge:")
    c.setFont("Helvetica", 9)
    c.drawString(120*mm, y, "☐ ja   ☒ nein" if not daten.get('mehrleistung') else "☒ ja   ☐ nein")

    # E) Vorbehalt
    y -= 8*mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20*mm, y, "E) Vorbehalt:")
    c.setFont("Helvetica", 9)
    c.drawString(45*mm, y, (daten.get('vorbehalt_text') or "—") if daten.get('mit_vorbehalt') else "keiner")

    # F) In Kraft ab
    y -= 8*mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20*mm, y, "F) Die Änderungen treten in Kraft ab:")
    c.setFont("Helvetica", 9)
    c.drawString(80*mm, y, wtxt)

    # Ort/Datum + Unterschrift
    y -= 16*mm
    absn = _absender(verwaltung, mandant)
    ort = (absn[2].split(' ', 1)[-1] if absn[2] else (lg.ort if lg else ''))
    import datetime as _dt
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20*mm, y, "Ort/Datum")
    c.drawString(110*mm, y, "Unterschrift")
    c.setFont("Helvetica", 9)
    c.drawString(45*mm, y, f"{ort}, ")
    if verwaltung and getattr(verwaltung, 'logo', None):
        pass
    mandant_unterschrift = getattr(mandant, 'unterschrift_bild', None) if mandant else None
    if mandant_unterschrift:
        try:
            c.drawImage(mandant_unterschrift.path, 110*mm, y - 12*mm, width=45*mm, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
    c.setFont("Helvetica-Oblique", 7.5)
    c.setFillColor(colors.grey)
    c.drawString(20*mm, 12*mm, "Das Formular ist nur gültig mit den Angaben der Schlichtungsbehörden und den Bestimmungen des OR (Seite 2).  Seite 1/2")
    c.setFillColor(colors.black)

    c.showPage()
    _schlichtung_seite(c, [
        "Der Mieter kann eine Mietzinserhöhung oder andere Mietvertragsänderung innert 30 Tagen, nachdem sie",
        "ihm mitgeteilt worden ist, bei der Schlichtungsbehörde als missbräuchlich im Sinne der Art. 269 und",
        "269a OR anfechten (Art. 270b OR).",
    ], kanton_name=kanton_name, behoerden=behoerden, exakt=exakt)
    c.drawRightString(190*mm, 12*mm, "Seite 2/2")
    c.showPage(); c.save(); buf.seek(0)
    return buf.read()


# ============================================================
# 2) KÜNDIGUNG (Art. 266l / 298 OR, Art. 9 VMWG)
# ============================================================
def kuendigung_so_pdf(vertrag, kuendigung, verwaltung=None):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    mieter = vertrag.mieter
    einheit = vertrag.einheit
    lg = einheit.liegenschaft
    mandant = lg.mandant if lg else None
    c.setTitle(f"Kündigung {mieter.nachname}")

    from core.services.kantone import schlichtung_block
    _kt, kanton_name, behoerden, exakt = schlichtung_block(lg)
    _kopf(c, "Amtliches Formular für Kündigung von vermieteten oder verpachteten Wohn- und Geschäftsräumen",
          kanton_name=kanton_name or "Solothurn")
    c.setFont("Helvetica-Bold", 8)
    c.drawString(110*mm, 278*mm, "Einschreiben R")

    c.setFont("Helvetica-Bold", 15)
    c.drawString(20*mm, 268*mm, "Kündigung von Wohn- und Geschäftsräumen")

    # Mieterschaft
    y = 256*mm
    c.setFont("Helvetica-Bold", 9); c.drawString(20*mm, y, "Mieterschaft")
    c.setFont("Helvetica", 9)
    c.drawString(70*mm, y, f"{mieter.vorname} {mieter.nachname}")
    if vertrag.mitmieter_id:
        c.drawString(70*mm, y - 5*mm, vertrag.mitmieter.display_name)
    elif vertrag.mitmieter_name:
        c.drawString(70*mm, y - 5*mm, vertrag.mitmieter_name)
    m_adr = f"{mieter.strasse or ''}, {mieter.plz or ''} {mieter.ort or ''}".strip(' ,')
    c.drawString(70*mm, y - 10*mm, m_adr)

    # Vermieterschaft
    y -= 22*mm
    c.setFont("Helvetica-Bold", 9); c.drawString(20*mm, y, "Vermieterschaft")
    c.setFont("Helvetica", 9)
    for i, line in enumerate(_absender(verwaltung, mandant)):
        c.drawString(70*mm, y - i*5*mm, line)

    # Objekt
    y -= 24*mm
    c.setFont("Helvetica-Bold", 9); c.drawString(20*mm, y, "Miet- / Pachtobjekt:")
    c.setFont("Helvetica", 9)
    c.drawString(70*mm, y, f"{einheit.bezeichnung}, {lg.strasse}, {lg.plz} {lg.ort}")

    # Kündigung des Vertrags vom / per
    y -= 12*mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20*mm, y, "Kündigung des Miet-/Pachtvertrags vom")
    c.setFont("Helvetica", 9)
    c.drawString(90*mm, y, vertrag.beginn.strftime('%d.%m.%Y') if vertrag.beginn else "")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(130*mm, y, "per")
    c.setFont("Helvetica", 9)
    per = getattr(kuendigung, 'per_datum', None) or getattr(kuendigung, 'berechneter_termin', None) or vertrag.ende
    c.drawString(140*mm, y, per.strftime('%d.%m.%Y') if per else "")

    # Begründung
    y -= 12*mm
    c.setFont("Helvetica-Bold", 9); c.drawString(20*mm, y, "Begründung")
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(20*mm, y - 4*mm, "Die Kündigung muss auf Verlangen begründet werden (Art. 271 Abs. 2 OR)")
    c.setFont("Helvetica", 9)
    grund = (getattr(kuendigung, 'ausserordentlich_grund', '') or getattr(kuendigung, 'bemerkung', '') or "").strip()
    yy = y - 11*mm
    for zeile in _wrap(grund or "—", 105):
        c.drawString(22*mm, yy, zeile); yy -= 5*mm

    # Hinweis Familienwohnung
    y = 120*mm
    c.setFont("Helvetica-Bold", 8.5); c.drawString(20*mm, y, "Hinweis (Art. 266n OR)")
    c.setFont("Helvetica", 7.5)
    for zeile in _wrap("Bei einer vermieteten Familienwohnung sind die Kündigung und die Ansetzung einer Zahlungsfrist "
                       "mit Kündigungsandrohung (Art. 257d OR) dem Mieter und seinem Ehegatten / eingetragenen Partner "
                       "einzeln und mit separater Post zuzustellen, ansonsten die Kündigung nichtig ist.", 118):
        c.drawString(20*mm, y - 4*mm, zeile); y -= 4*mm

    # Ort/Datum + Unterschrift
    y = 95*mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20*mm, y, "Ort / Datum")
    c.drawString(110*mm, y, "Unterschrift")
    absn = _absender(verwaltung, mandant)
    ort = (absn[2].split(' ', 1)[-1] if absn[2] else (lg.ort if lg else ''))
    c.setFont("Helvetica", 9)
    c.drawString(20*mm, y - 8*mm, f"{ort}, ")
    mandant_unterschrift = getattr(mandant, 'unterschrift_bild', None) if mandant else None
    if mandant_unterschrift:
        try:
            c.drawImage(mandant_unterschrift.path, 110*mm, y - 20*mm, width=45*mm, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass

    c.setFont("Helvetica-Oblique", 7.5); c.setFillColor(colors.grey)
    c.drawString(20*mm, 12*mm, "Das Formular ist nur gültig mit den Bestimmungen des OR (Seite 2).  Seite 1/2")
    c.setFillColor(colors.black)

    c.showPage()
    _schlichtung_seite(c, [
        "Die Mieterschaft kann innert 30 Tagen nach Empfang dieser Mitteilung bei der Schlichtungsbehörde die",
        "Kündigung anfechten und/oder die Erstreckung des Mietverhältnisses verlangen (Art. 273 OR).",
        "Bei der Pacht gilt dies sinngemäss (Art. 300 OR).",
    ], kanton_name=kanton_name, behoerden=behoerden, exakt=exakt)
    c.drawRightString(190*mm, 12*mm, "Seite 2/2")
    c.showPage(); c.save(); buf.seek(0)
    return buf.read()


def _wrap(text, breite=100):
    worte = (text or "").split()
    zeilen, akt = [], ""
    for w in worte:
        if len(akt) + len(w) + 1 > breite:
            zeilen.append(akt); akt = w
        else:
            akt = (akt + " " + w).strip()
    if akt:
        zeilen.append(akt)
    return zeilen or [""]

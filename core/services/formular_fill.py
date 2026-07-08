"""Füllt die AMTLICHEN Original-Formulare (Kanton Solothurn) aus, indem die Daten
per Overlay auf das unveränderte Original-PDF gestempelt werden. Der Formularinhalt
(Layout, Gesetzestexte Seite 2, Schlichtungsbehörden) bleibt exakt das Original."""
import io
import os
import datetime
from decimal import Decimal

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from pypdf import PdfReader, PdfWriter

_DIR = os.path.join(os.path.dirname(__file__), 'formulare')
SO_MIETZINS = os.path.join(_DIR, 'SO_mietzins_original.pdf')
SO_KUENDIGUNG = os.path.join(_DIR, 'SO_kuendigung_original.pdf')

PAGE_H = 842.0  # A4 pt (595 x 842), Original-Formulare


def _fr(d):
    try:
        return f"{Decimal(str(d)):,.2f}".replace(",", "'")
    except Exception:
        return ""


def _y(top):
    """pdfplumber top-origin → reportlab bottom-origin (Textbasislinie in der Box)."""
    return PAGE_H - top - 10


def _overlay(zeichnen):
    """Erzeugt ein 1-seitiges Overlay-PDF (A4) und ruft zeichnen(canvas) auf."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 9)
    zeichnen(c)
    c.showPage(); c.save(); buf.seek(0)
    return PdfReader(buf).pages[0]


def _merge(original_pfad, overlay_page):
    reader = PdfReader(original_pfad)
    writer = PdfWriter()
    p0 = reader.pages[0]
    p0.merge_page(overlay_page)
    writer.add_page(p0)
    for p in reader.pages[1:]:      # Seite 2 (Gesetzestexte) unverändert
        writer.add_page(p)
    out = io.BytesIO()
    writer.write(out); out.seek(0)
    return out.read()


def _absender(verwaltung, mandant):
    if mandant:
        return [mandant.firma_oder_name, mandant.strasse or "", f"{mandant.plz or ''} {mandant.ort or ''}".strip()]
    if verwaltung:
        return [verwaltung.firma or "", verwaltung.strasse or "", f"{verwaltung.plz or ''} {verwaltung.ort or ''}".strip()]
    return ["Immobilienverwaltung", "", ""]


def _wrap(text, breite):
    worte = (text or "").split()
    zeilen, akt = [], ""
    for w in worte:
        if len(akt) + len(w) + 1 > breite:
            zeilen.append(akt); akt = w
        else:
            akt = (akt + " " + w).strip()
    if akt:
        zeilen.append(akt)
    return zeilen


# ============================================================
# MIETZINSANPASSUNG — Original SO ausfüllen
# ============================================================
def fill_mietzins_so(vertrag, daten, verwaltung=None):
    mieter = vertrag.mieter
    einheit = vertrag.einheit
    lg = einheit.liegenschaft
    mandant = lg.mandant if lg else None
    absn = _absender(verwaltung, mandant)
    ort_kopf = (absn[2].split(' ', 1)[-1] if absn[2] else (lg.ort if lg else ''))
    heute = datetime.date.today()
    wirksam = daten['wirksam_ab']
    wtxt = wirksam.strftime('%d.%m.%Y') if hasattr(wirksam, 'strftime') else str(wirksam)

    alt_netto = Decimal(str(daten['alt_netto']))
    neu_netto = Decimal(str(daten['neu_netto']))
    nk = Decimal(str(daten.get('nebenkosten') or 0))

    gruende = []
    if daten.get('alt_zins') is not None and daten.get('neu_zins') is not None and daten['alt_zins'] != daten['neu_zins']:
        gruende.append(f"Anpassung an den Referenzzinssatz: {daten['alt_zins']} % auf {daten['neu_zins']} %.")
    if daten.get('alt_lik') is not None and daten.get('neu_lik') is not None and daten['alt_lik'] != daten['neu_lik']:
        gruende.append(f"Teuerungsausgleich (LIK): {daten['alt_lik']} auf {daten['neu_lik']} Punkte (40 % anrechenbar).")
    if daten.get('kosten_pct'):
        gruende.append(f"Allgemeine Kostensteigerung: {daten.get('kosten_pct')} %.")
    if daten.get('begruendung'):
        gruende.append(daten['begruendung'])
    if not gruende:
        gruende = ["Anpassung an die aktuellen Grundlagen (Referenzzinssatz und Teuerung)."]

    def zeichnen(c):
        c.setFont("Helvetica", 9)
        # Absender
        for i, line in enumerate(absn):
            c.drawString(78, _y(120 + i*11), line)
        # Adressat (Einschreiben R ist vorgedruckt)
        c.drawString(319, _y(126), f"{mieter.vorname} {mieter.nachname}")
        c.drawString(319, _y(138), mieter.strasse or "")
        c.drawString(319, _y(150), f"{mieter.plz or ''} {mieter.ort or ''}".strip())
        # Nachtrag-Nr + Mietvertrag vom + Objekt
        c.drawString(400, _y(198), vertrag.beginn.strftime('%d.%m.%Y') if vertrag.beginn else "")
        c.drawString(142, _y(218), f"{einheit.bezeichnung}, {lg.strasse}, {lg.plz} {lg.ort}")
        # neu ab (Tabellenkopf)
        c.drawString(463, _y(309), wtxt)
        # Nettomietzins bisher/neu
        c.drawString(318, _y(330), _fr(alt_netto))
        c.drawString(451, _y(330), _fr(neu_netto))
        # Neben-/Betriebskosten total → erste freie Positionszeile (top≈466)
        c.drawString(76, _y(467), "Neben-/Betriebskosten")
        c.drawString(318, _y(467), _fr(nk))
        c.drawString(451, _y(467), _fr(nk))
        # Bruttomietzins (top≈518)
        c.drawString(318, _y(519), _fr(alt_netto + nk))
        c.drawString(451, _y(519), _fr(neu_netto + nk))
        # C) Begründung (Box top≈588..663)
        yy = 598
        for g in gruende:
            for zeile in _wrap(g, 62):
                c.drawString(220, _y(yy), zeile); yy += 11
        # E) Vorbehalt
        if daten.get('mit_vorbehalt'):
            c.drawString(319, _y(694), (daten.get('vorbehalt_text') or "Weitere Erhöhungsgründe vorbehalten")[:55])
        # F) in Kraft ab
        c.drawString(319, _y(715), wtxt)
        # Ort/Datum
        c.drawString(142, _y(740), f"{ort_kopf}, {heute.strftime('%d.%m.%Y')}")
        # Unterschrift (mechanisch, zulässig Art. 269d Abs. 4)
        us = getattr(mandant, 'unterschrift_bild', None) if mandant else None
        if us:
            try:
                c.drawImage(us.path, 400, _y(755) - 4, width=110, height=22, preserveAspectRatio=True, mask='auto')
            except Exception:
                pass

    return _merge(SO_MIETZINS, _overlay(zeichnen))


# ============================================================
# KÜNDIGUNG — Original SO ausfüllen
# ============================================================
def fill_kuendigung_so(vertrag, kuendigung, verwaltung=None):
    mieter = vertrag.mieter
    einheit = vertrag.einheit
    lg = einheit.liegenschaft
    mandant = lg.mandant if lg else None
    absn = _absender(verwaltung, mandant)
    ort_kopf = (absn[2].split(' ', 1)[-1] if absn[2] else (lg.ort if lg else ''))
    heute = datetime.date.today()
    per = getattr(kuendigung, 'per_datum', None) or getattr(kuendigung, 'berechneter_termin', None) or vertrag.ende
    grund = (getattr(kuendigung, 'ausserordentlich_grund', '') or getattr(kuendigung, 'bemerkung', '') or "").strip()

    mit2 = ""
    if vertrag.mitmieter_id:
        mit2 = vertrag.mitmieter.display_name
    elif vertrag.mitmieter_name:
        mit2 = vertrag.mitmieter_name

    def zeichnen(c):
        c.setFont("Helvetica", 9)
        # Mieterschaft
        c.drawString(165, _y(155), f"{mieter.vorname} {mieter.nachname}")
        if mit2:
            c.drawString(165, _y(174), mit2)
            c.drawString(165, _y(194), f"{mieter.strasse or ''}, {mieter.plz or ''} {mieter.ort or ''}".strip(' ,'))
        else:
            c.drawString(165, _y(174), f"{mieter.strasse or ''}, {mieter.plz or ''} {mieter.ort or ''}".strip(' ,'))
        # Vermieterschaft
        for i, line in enumerate(absn):
            c.drawString(165, _y(224 + i*19), line)
        # Objekt
        c.drawString(165, _y(293), f"{einheit.bezeichnung}, {lg.strasse}, {lg.plz} {lg.ort}")
        # Vertrag vom / per
        c.drawString(267, _y(327), vertrag.beginn.strftime('%d.%m.%Y') if vertrag.beginn else "")
        c.drawString(418, _y(327), per.strftime('%d.%m.%Y') if per else "")
        # Begründung (Box top≈384..454)
        yy = 394
        for zeile in _wrap(grund or "—", 92):
            c.drawString(76, _y(yy), zeile); yy += 11
        # Ort/Datum
        c.drawString(76, _y(562), f"{ort_kopf}, {heute.strftime('%d.%m.%Y')}")
        us = getattr(mandant, 'unterschrift_bild', None) if mandant else None
        if us:
            try:
                c.drawImage(us.path, 330, _y(575) - 4, width=110, height=22, preserveAspectRatio=True, mask='auto')
            except Exception:
                pass

    return _merge(SO_KUENDIGUNG, _overlay(zeichnen))

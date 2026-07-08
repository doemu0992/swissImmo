"""Füllt die AMTLICHEN Original-Formulare der Kantone aus. Der Formularinhalt
(Layout, Gesetzestexte, Schlichtungsbehörden) bleibt exakt das Original — nur die
Datenfelder werden befüllt.

Zwei Techniken je nach Original:
- Kantone mit ausfüllbaren PDF-Formularfeldern (AcroForm: ZH, BE, …) → Felder direkt
  über ihren Feldnamen befüllen (sauberste Variante, keine Koordinaten).
- Kantone ohne Formularfelder (SO) → Daten per Overlay auf das Original stempeln."""
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


# ============================================================
# GENERISCHER ACROFORM-FÜLLER (für Kantone mit ausfüllbaren PDF-Feldern)
# ============================================================
def _checkbox_on_states(reader):
    """Ermittelt pro Checkbox-Feld den echten 'An'-Zustand (z.B. '/Ja', '/Yes')."""
    states = {}
    for page in reader.pages:
        for a in (page.get('/Annots') or []):
            o = a.get_object()
            parent = o.get('/Parent')
            ft = o.get('/FT') or (parent and parent.get_object().get('/FT'))
            if ft != '/Btn':
                continue
            name = o.get('/T') or (parent and parent.get_object().get('/T'))
            ap = o.get('/AP')
            if ap and ap.get('/N'):
                for k in ap['/N'].keys():
                    if k != '/Off':
                        states[str(name)] = k
    return states


def _fill_acroform(original_pfad, text_values, checkbox_fields=()):
    """Befüllt ein AcroForm-PDF. text_values: {feldname: text}. checkbox_fields: Liste
    von Feldnamen, die angekreuzt werden. Seiten/Recht/Layout bleiben unverändert."""
    reader = PdfReader(original_pfad)
    writer = PdfWriter()
    writer.append(reader)

    on = _checkbox_on_states(reader)
    werte = {k: ('' if v is None else str(v)) for k, v in text_values.items()}
    for cf in checkbox_fields:
        werte[cf] = on.get(cf, '/Yes')

    for page in writer.pages:
        try:
            writer.update_page_form_field_values(page, werte, auto_regenerate=False)
        except Exception:
            pass
    try:
        writer.set_need_appearances_writer(True)  # Viewer rendert die Werte
    except Exception:
        pass

    out = io.BytesIO()
    writer.write(out); out.seek(0)
    return out.read()


def _mieter_block(mieter, sep='\n'):
    zeilen = [f"{mieter.vorname} {mieter.nachname}".strip()]
    if mieter.strasse:
        zeilen.append(mieter.strasse)
    ort = f"{mieter.plz or ''} {mieter.ort or ''}".strip()
    if ort:
        zeilen.append(ort)
    return sep.join(zeilen)


def _absender_block(verwaltung, mandant, sep='\n'):
    return sep.join(t for t in _absender(verwaltung, mandant) if t)


def _mitmieter_block(vertrag, sep='\n'):
    if vertrag.mitmieter_id:
        m = vertrag.mitmieter
        zeilen = [m.display_name]
        if m.strasse:
            zeilen.append(m.strasse)
        ort = f"{m.plz or ''} {m.ort or ''}".strip()
        if ort:
            zeilen.append(ort)
        return sep.join(zeilen)
    if vertrag.mitmieter_name:
        return vertrag.mitmieter_name
    return ''


def _objekt_zeile(vertrag):
    e = vertrag.einheit
    lg = e.liegenschaft
    return f"{e.bezeichnung}, {lg.strasse}, {lg.plz} {lg.ort}"


def _dstr(d):
    return d.strftime('%d.%m.%Y') if hasattr(d, 'strftime') and d else ''


def _ort_datum(vertrag, verwaltung, mandant):
    absn = _absender(verwaltung, mandant)
    ort = (absn[2].split(' ', 1)[-1] if absn[2] else '') or (vertrag.einheit.liegenschaft.ort or '')
    return f"{ort}, {datetime.date.today().strftime('%d.%m.%Y')}"


# ============================================================
# ZÜRICH — amtliche Originale (AcroForm)
# ============================================================
def fill_mietzins_zh(vertrag, daten, verwaltung=None):
    mieter = vertrag.mieter
    lg = vertrag.einheit.liegenschaft
    mandant = lg.mandant if lg else None
    alt = Decimal(str(daten['alt_netto'])); neu = Decimal(str(daten['neu_netto']))
    nk = Decimal(str(daten.get('nebenkosten') or 0))
    absn_block = _absender_block(verwaltung, mandant)

    gruende = []
    if daten.get('alt_zins') is not None and daten.get('neu_zins') is not None and daten['alt_zins'] != daten['neu_zins']:
        gruende.append(f"Referenzzinssatz: {daten['alt_zins']} % auf {daten['neu_zins']} %.")
    if daten.get('alt_lik') is not None and daten.get('neu_lik') is not None and daten['alt_lik'] != daten['neu_lik']:
        gruende.append(f"Teuerung (LIK): {daten['alt_lik']} auf {daten['neu_lik']} Punkte (40 % anrechenbar).")
    if daten.get('kosten_pct'):
        gruende.append(f"Allgemeine Kostensteigerung: {daten.get('kosten_pct')} %.")
    if daten.get('begruendung'):
        gruende.append(daten['begruendung'])
    if not gruende:
        gruende = ["Anpassung an Referenzzinssatz und Teuerung."]
    g_zeilen = []
    for g in gruende:
        g_zeilen += _wrap(g, 88)

    tv = {
        'Einschreiben Feld Adresseingabe LINKS 4': _mieter_block(mieter),
        'Einschreiben Feld Adresseingabe 1 RECHTS 4': _mitmieter_block(vertrag),
        'Absender/in Text Eingabefeld 4': absn_block,
        'Textfeld 73': _absender_block(verwaltung, mandant, sep=', '),
        'Textfeld 4': vertrag.einheit.bezeichnung,
        'Textfeld 5': f"{lg.strasse}, {lg.plz} {lg.ort}",
        'Textfeld 6': _dstr(daten['wirksam_ab']),
        'Textfeld 7': _fr(alt), 'Textfeld 8': _fr(neu),
        'Textfeld 9': 'Nebenkosten' if nk else '',
        'Textfeld 10': _fr(nk) if nk else '', 'Textfeld 11': _fr(nk) if nk else '',
        'Textfeld 30': _fr(alt + nk), 'Textfeld 31': _fr(neu + nk),
        'Textfeld 32': g_zeilen[0] if len(g_zeilen) > 0 else '',
        'Textfeld 76': g_zeilen[1] if len(g_zeilen) > 1 else '',
        'Textfeld 74': g_zeilen[2] if len(g_zeilen) > 2 else '',
        'Textfeld 75': g_zeilen[3] if len(g_zeilen) > 3 else '',
        'Textfeld 69': _ort_datum(vertrag, verwaltung, mandant),
    }
    cbs = ['Kontrollkästchen 1', 'Kontrollkästchen 3']  # Wohnung + Mietzinserhöhung
    return _fill_acroform(os.path.join(_DIR, 'ZH_mietzins_original.pdf'), tv, cbs)


def fill_kuendigung_zh(vertrag, kuendigung, verwaltung=None):
    mieter = vertrag.mieter
    lg = vertrag.einheit.liegenschaft
    mandant = lg.mandant if lg else None
    per = getattr(kuendigung, 'per_datum', None) or getattr(kuendigung, 'berechneter_termin', None) or vertrag.ende
    grund = (getattr(kuendigung, 'ausserordentlich_grund', '') or getattr(kuendigung, 'bemerkung', '') or '').strip()
    g_zeilen = _wrap(grund, 92) if grund else []

    tv = {
        'Einschreiben Feld Adresseingabe LINKS 5': _mieter_block(mieter),
        'Einschreiben Feld Adresseingabe 1 RECHTS 5': _mitmieter_block(vertrag),
        'Absender/in Text Eingabefeld 5': _absender_block(verwaltung, mandant),
        'Vermieter/in Feld Texteingabe 7': _absender_block(verwaltung, mandant),
        'Textfeld 8': vertrag.einheit.bezeichnung,
        'Textfeld 9': f"{lg.strasse}, {lg.plz} {lg.ort}",
        'Textfeld 12': _dstr(per),
        'Textfeld 111': _ort_datum(vertrag, verwaltung, mandant),
    }
    for i, z in enumerate(g_zeilen[:8]):
        tv[f'Textfeld {13 + i}'] = z
    cbs = ['Kontrollkästchen 4', 'Kontrollkästchen 6', 'Kontrollkästchen 10']  # Miete + Wohnung + Mietvertrag
    return _fill_acroform(os.path.join(_DIR, 'ZH_kuendigung_original.pdf'), tv, cbs)


# ============================================================
# BERN — amtliche Originale (AcroForm)
# ============================================================
def fill_mietzins_be(vertrag, daten, verwaltung=None):
    mieter = vertrag.mieter
    lg = vertrag.einheit.liegenschaft
    mandant = lg.mandant if lg else None
    alt = Decimal(str(daten['alt_netto'])); neu = Decimal(str(daten['neu_netto']))
    nk = Decimal(str(daten.get('nebenkosten') or 0))
    absn = _absender(verwaltung, mandant)

    gruende = []
    if daten.get('alt_zins') is not None and daten.get('neu_zins') is not None and daten['alt_zins'] != daten['neu_zins']:
        gruende.append(f"Referenzzinssatz {daten['alt_zins']} % auf {daten['neu_zins']} %.")
    if daten.get('alt_lik') is not None and daten.get('neu_lik') is not None and daten['alt_lik'] != daten['neu_lik']:
        gruende.append(f"Teuerung (LIK) {daten['alt_lik']} auf {daten['neu_lik']} Punkte (40 %).")
    if daten.get('kosten_pct'):
        gruende.append(f"Kostensteigerung {daten.get('kosten_pct')} %.")
    if daten.get('begruendung'):
        gruende.append(daten['begruendung'])
    begr = ' '.join(gruende) or 'Anpassung an Referenzzinssatz und Teuerung.'

    # Vermieter links (Textfeld 1-4), Mieter rechts (Textfeld 5-8),
    # Vertreter/in links (Textfeld 9-11), Miet-/Pachtobjekt (Textfeld 13)
    tv = {
        'Textfeld 1': absn[0], 'Textfeld 2': absn[1], 'Textfeld 3': absn[2],
        'Textfeld 5': f"{mieter.vorname} {mieter.nachname}".strip(),
        'Textfeld 6': mieter.strasse or '',
        'Textfeld 7': f"{mieter.plz or ''} {mieter.ort or ''}".strip(),
        'Textfeld 8': _mitmieter_block(vertrag, sep=', '),
        'Textfeld 9': absn[0], 'Textfeld 10': absn[1], 'Textfeld 11': absn[2],  # Vertreter/in
        'Textfeld 13': _objekt_zeile(vertrag),                          # Miet-/Pachtobjekt
        'Textfeld 14': _dstr(daten['wirksam_ab']),                      # neu ab
        'Textfeld 15': _fr(alt), 'Textfeld 16': _fr(neu),               # Zins ohne NK bisher/neu
        'Textfeld 17': _fr(nk) if nk else '', 'Textfeld 18': _fr(nk) if nk else '',  # NK
        'Textfeld 19': begr[:110],                                      # klare Begründung der Änderung
        'Ort_Datum': _ort_datum(vertrag, verwaltung, mandant),
        'Unterschrift': '',
    }
    cbs = ['Modification du loyer fermage']  # Miet-/Pachtzinsänderung
    return _fill_acroform(os.path.join(_DIR, 'BE_mietzins_original.pdf'), tv, cbs)


def fill_kuendigung_be(vertrag, kuendigung, verwaltung=None):
    mieter = vertrag.mieter
    lg = vertrag.einheit.liegenschaft
    mandant = lg.mandant if lg else None
    absn = _absender(verwaltung, mandant)
    per = getattr(kuendigung, 'per_datum', None) or getattr(kuendigung, 'berechneter_termin', None) or vertrag.ende
    grund = (getattr(kuendigung, 'ausserordentlich_grund', '') or getattr(kuendigung, 'bemerkung', '') or '').strip()

    mit = _mitmieter_block(vertrag, sep=', ')
    tv = {
        # Vermieter links (Textfeld 1-5)
        'Textfeld 1': absn[0], 'Textfeld 2': absn[1], 'Textfeld 3': absn[2],
        # Mieter rechts (Textfeld 6-10)
        'Textfeld 6': f"{mieter.vorname} {mieter.nachname}".strip(),
        'Textfeld 7': mieter.strasse or '',
        'Textfeld 8': f"{mieter.plz or ''} {mieter.ort or ''}".strip(),
        'Textfeld 9': mit,
        # Vertreter/in (Textfeld 11-15)
        'Textfeld 11': _absender(verwaltung, mandant)[0],
        'Textfeld 12': _absender(verwaltung, mandant)[1],
        'Textfeld 13': _absender(verwaltung, mandant)[2],
        # Objekt / Daten / Begründung
        'Textfeld 16': _objekt_zeile(vertrag),
        'Textfeld 17': _dstr(vertrag.beginn),
        'Textfeld 18': _dstr(per),
        'Textfeld 19': grund,
        'Ort / Datum': _ort_datum(vertrag, verwaltung, mandant),
    }
    return _fill_acroform(os.path.join(_DIR, 'BE_kuendigung_original.pdf'), tv, ())


# ============================================================
# DISPATCHER — Kanton automatisch wählen
# ============================================================
# Kantone mit eingebautem Original-Formular.
_MIETZINS_FILLER = {
    'SO': fill_mietzins_so,
    'ZH': fill_mietzins_zh,
    'BE': fill_mietzins_be,
}
_KUENDIGUNG_FILLER = {
    'SO': fill_kuendigung_so,
    'ZH': fill_kuendigung_zh,
    'BE': fill_kuendigung_be,
}


def hat_original(kanton, typ):
    reg = _MIETZINS_FILLER if typ == 'mietzins' else _KUENDIGUNG_FILLER
    return (kanton or '').upper() in reg


def fill_mietzins(vertrag, daten, verwaltung=None, kanton=None):
    """Füllt das amtliche Mietzins-Formular des passenden Kantons. Gibt None zurück,
    wenn für den Kanton (noch) kein Original hinterlegt ist."""
    from core.services.kantone import kanton_fuer_liegenschaft
    kt = (kanton or kanton_fuer_liegenschaft(vertrag.einheit.liegenschaft) or '').upper()
    fn = _MIETZINS_FILLER.get(kt)
    return fn(vertrag, daten, verwaltung=verwaltung) if fn else None


def fill_kuendigung(vertrag, kuendigung, verwaltung=None, kanton=None):
    from core.services.kantone import kanton_fuer_liegenschaft
    kt = (kanton or kanton_fuer_liegenschaft(vertrag.einheit.liegenschaft) or '').upper()
    fn = _KUENDIGUNG_FILLER.get(kt)
    return fn(vertrag, kuendigung, verwaltung=verwaltung) if fn else None

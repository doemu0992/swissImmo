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
def fill_kuendigung_so(vertrag, kuendigung, verwaltung=None, empfaenger=None):
    mieter = vertrag.mieter
    einheit = vertrag.einheit
    lg = einheit.liegenschaft
    mandant = lg.mandant if lg else None
    absn = _absender(verwaltung, mandant)
    ort_kopf = (absn[2].split(' ', 1)[-1] if absn[2] else (lg.ort if lg else ''))
    heute = datetime.date.today()
    per = getattr(kuendigung, 'per_datum', None) or getattr(kuendigung, 'berechneter_termin', None) or vertrag.ende
    grund = (getattr(kuendigung, 'ausserordentlich_grund', '') or getattr(kuendigung, 'bemerkung', '') or "").strip()

    # Art. 266n: getrennte Zustellung → nur der eine Ehegatte in der Adresse.
    if empfaenger is not None:
        e_name, e_adr, mit2 = empfaenger.name, f"{empfaenger.strasse or ''}, {empfaenger.plz or ''} {empfaenger.ort or ''}".strip(' ,'), ""
    else:
        e_name = f"{mieter.vorname} {mieter.nachname}"
        e_adr = f"{mieter.strasse or ''}, {mieter.plz or ''} {mieter.ort or ''}".strip(' ,')
        mit2 = vertrag.mitmieter.display_name if vertrag.mitmieter_id else (vertrag.mitmieter_name or "")

    def zeichnen(c):
        c.setFont("Helvetica", 9)
        # Mieterschaft
        c.drawString(165, _y(155), e_name)
        if mit2:
            c.drawString(165, _y(174), mit2)
            c.drawString(165, _y(194), e_adr)
        else:
            c.drawString(165, _y(174), e_adr)
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


# ---- Einzel-Empfänger (Art. 266n: getrennte Zustellung je Ehegatte) ----
from collections import namedtuple as _nt
Empfaenger = _nt('Empfaenger', ['name', 'strasse', 'plz', 'ort'])


def _empf_block(e, sep='\n'):
    zeilen = [e.name.strip()]
    if e.strasse:
        zeilen.append(e.strasse)
    ort = f"{e.plz or ''} {e.ort or ''}".strip()
    if ort:
        zeilen.append(ort)
    return sep.join(z for z in zeilen if z)


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
    # Objekt-Art aus der mietrechtlichen Kategorie ableiten (nicht hart «Wohnung»):
    # Kontrollkästchen 1 = Wohnung, 2 = Geschäftsräume. Wohnzweck-Objekte (wohnen)
    # kreuzen Wohnung; Gewerbe/Geschäft kreuzt Geschäftsräume.
    obj_cb = 'Kontrollkästchen 1' if vertrag.mietrecht_kategorie == 'wohnen' else 'Kontrollkästchen 2'
    cbs = [obj_cb, 'Kontrollkästchen 3']  # Objekt-Art + Mietzinserhöhung
    return _fill_acroform(os.path.join(_DIR, 'ZH_mietzins_original.pdf'), tv, cbs)


def fill_kuendigung_zh(vertrag, kuendigung, verwaltung=None, empfaenger=None):
    mieter = vertrag.mieter
    lg = vertrag.einheit.liegenschaft
    mandant = lg.mandant if lg else None
    per = getattr(kuendigung, 'per_datum', None) or getattr(kuendigung, 'berechneter_termin', None) or vertrag.ende
    grund = (getattr(kuendigung, 'ausserordentlich_grund', '') or getattr(kuendigung, 'bemerkung', '') or '').strip()
    g_zeilen = _wrap(grund, 92) if grund else []

    # Art. 266n: getrennte Zustellung → nur der eine Ehegatte im Adressfeld links.
    adr_links = _empf_block(empfaenger) if empfaenger is not None else _mieter_block(mieter)
    adr_rechts = '' if empfaenger is not None else _mitmieter_block(vertrag)
    tv = {
        'Einschreiben Feld Adresseingabe LINKS 5': adr_links,
        'Einschreiben Feld Adresseingabe 1 RECHTS 5': adr_rechts,
        'Absender/in Text Eingabefeld 5': _absender_block(verwaltung, mandant),
        'Vermieter/in Feld Texteingabe 7': _absender_block(verwaltung, mandant),
        'Textfeld 8': vertrag.einheit.bezeichnung,
        'Textfeld 9': f"{lg.strasse}, {lg.plz} {lg.ort}",
        'Textfeld 12': _dstr(per),
        'Textfeld 111': _ort_datum(vertrag, verwaltung, mandant),
    }
    for i, z in enumerate(g_zeilen[:8]):
        tv[f'Textfeld {13 + i}'] = z
    # Objekt-Art aus der mietrechtlichen Kategorie: Kontrollkästchen 6 = Wohnung,
    # 7 = Geschäftsräume. Wohnzweck-Objekte kreuzen Wohnung, Gewerbe Geschäftsräume.
    obj_cb = 'Kontrollkästchen 6' if vertrag.mietrecht_kategorie == 'wohnen' else 'Kontrollkästchen 7'
    cbs = ['Kontrollkästchen 4', obj_cb, 'Kontrollkästchen 10']  # Mietverhältnis + Objekt-Art + Mietvertrag
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


def fill_kuendigung_be(vertrag, kuendigung, verwaltung=None, empfaenger=None):
    mieter = vertrag.mieter
    lg = vertrag.einheit.liegenschaft
    mandant = lg.mandant if lg else None
    absn = _absender(verwaltung, mandant)
    per = getattr(kuendigung, 'per_datum', None) or getattr(kuendigung, 'berechneter_termin', None) or vertrag.ende
    grund = (getattr(kuendigung, 'ausserordentlich_grund', '') or getattr(kuendigung, 'bemerkung', '') or '').strip()

    # Art. 266n: getrennte Zustellung → nur der eine Ehegatte im Mieterfeld.
    if empfaenger is not None:
        m_name, m_str, m_ort, mit = empfaenger.name, empfaenger.strasse or '', f"{empfaenger.plz or ''} {empfaenger.ort or ''}".strip(), ''
    else:
        m_name = f"{mieter.vorname} {mieter.nachname}".strip()
        m_str = mieter.strasse or ''
        m_ort = f"{mieter.plz or ''} {mieter.ort or ''}".strip()
        mit = _mitmieter_block(vertrag, sep=', ')
    tv = {
        # Vermieter links (Textfeld 1-5)
        'Textfeld 1': absn[0], 'Textfeld 2': absn[1], 'Textfeld 3': absn[2],
        # Mieter rechts (Textfeld 6-10)
        'Textfeld 6': m_name,
        'Textfeld 7': m_str,
        'Textfeld 8': m_ort,
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


def fill_anfangsmietzins_be(vertrag, daten, verwaltung=None):
    """Kanton Bern — «Formular zur Mitteilung des Anfangsmietzinses von Wohn-
    räumen» (Art. 270 Abs. 2 OR, Art. 135a EG ZGB). Feldnamen aus dem amtlichen
    Original (BE_anfangsmietzins_original.pdf, Obergericht BE 11/2025)."""
    mieter = vertrag.mieter
    einheit = vertrag.einheit
    lg = einheit.liegenschaft
    mandant = lg.mandant if lg else None
    # Vermieter = Eigentümer (Mandant); Vertreter/in = Verwaltung. Ohne Mandant
    # tritt die Verwaltung selbst als Vermieter auf.
    if mandant:
        vermieter = _absender(None, mandant)
        vertreter = _absender(verwaltung, None) if verwaltung else ['', '', '']
    else:
        vermieter = _absender(verwaltung, None)
        vertreter = ['', '', '']

    def _d(x):
        try:
            s = str(x).replace("'", '').replace(',', '.').strip()
            return Decimal(s) if s not in ('', 'None') else Decimal('0')
        except Exception:
            return Decimal('0')
    anf_netto, anf_nk = _d(daten.get('anfang_netto')), _d(daten.get('anfang_nk'))
    vor_netto, vor_nk = _d(daten.get('vormiete_netto')), _d(daten.get('vormiete_nk'))
    hat_vormiete = (vor_netto > 0 or vor_nk > 0)
    beginn = daten.get('beginn') or vertrag.beginn

    tv = {
        # Vermieter/in (Eigentümer) links, Mieter/in rechts
        'Textfeld 1': vermieter[0], 'Textfeld 2': vermieter[1], 'Textfeld 3': vermieter[2], 'Textfeld 4': '',
        'Textfeld 5': f"{mieter.vorname} {mieter.nachname}".strip(),
        'Textfeld 6': mieter.strasse or '',
        'Textfeld 7': f"{mieter.plz or ''} {mieter.ort or ''}".strip(),
        'Textfeld 8': _mitmieter_block(vertrag, sep=', '),
        # Vertreter/in (Verwaltung)
        'Textfeld 9': vertreter[0], 'Textfeld 10': vertreter[1], 'Textfeld 11': vertreter[2], 'Textfeld 12': '',
        # Liegenschaft / Mietobjekt / Beginn
        'Textfeld 13': f"{lg.strasse}, {lg.plz} {lg.ort}".strip(' ,'),
        'Textfeld 13a': einheit.bezeichnung,
        'Textfeld 13b': _dstr(beginn),
        # 1. Mietzins — Datumsangaben: bisheriger «seit» (leer bei Erstvermietung),
        #    Anfangsmietzins «ab» = Mietbeginn
        'Textfeld 14': _dstr(daten.get('vormiete_seit')) if hat_vormiete else '',
        'Textfeld 14a': _dstr(beginn),
        # Mietzins ohne NK | Nebenkosten | Total — je bisher (leer bei Erstverm.) / neu
        'Textfeld 15': _fr(vor_netto) if hat_vormiete else '', 'Textfeld 16': _fr(anf_netto),
        'Textfeld 17': _fr(vor_nk) if hat_vormiete else '', 'Textfeld 18': _fr(anf_nk),
        'Textfeld 19': _fr(vor_netto + vor_nk) if hat_vormiete else '', 'Textfeld 20': _fr(anf_netto + anf_nk),
        # Berechnungsgrundlagen bisheriger Mietzins (nur wenn bekannt)
        'Textfeld 21': str(daten.get('basis_ref') or ''),
        'Textfeld 22': str(daten.get('basis_lik') or ''),
        'Textfeld 22a': str(daten.get('basis_lik_basis') or ''),
        # 2. Vorbehalte · 3. Klare Begründung
        'Textfeld 23': (daten.get('vorbehalte') or '')[:220],
        'Textfeld 24': (daten.get('begruendung') or '')[:220],
        # Seite 2: Ort/Datum + Unterschrift Vermieter/in (Mieter unterschreibt selbst)
        'Ort und Datum 1': _ort_datum(vertrag, verwaltung, mandant),
        'Unterschrift Vermieter/in': '', 'Ort und Datum 2': '', 'Unterschrift Mieter/in': '',
    }
    # Förderbeiträge für wertvermehrende Verbesserungen: Standard «Nein».
    cbs = ['Ja'] if daten.get('foerderbeitraege') else ['Nein']
    return _fill_acroform(os.path.join(_DIR, 'BE_anfangsmietzins_original.pdf'), tv, cbs)


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
# Anfangsmietzins-Formular (Art. 270 Abs. 2 OR): Kantone mit hinterlegtem
# AcroForm-Original. Der Filler wird nur verwendet, wenn die zugehörige
# `<KT>_anfangsmietzins_original.pdf` tatsächlich im Ordner liegt (siehe
# fill_anfangsmietzins) — sonst greift das kanton-adaptive Fallback-Formular.
_ANFANG_FILLER = {
    'BE': fill_anfangsmietzins_be,   # amtliches Original Obergericht BE 11/2025
}


def hat_original(kanton, typ):
    kt = (kanton or '').upper()
    if typ == 'anfangsmietzins':
        # Original zählt nur, wenn Filler UND Template-Datei vorhanden sind.
        return kt in _ANFANG_FILLER and os.path.exists(
            os.path.join(_DIR, f'{kt}_anfangsmietzins_original.pdf'))
    reg = _MIETZINS_FILLER if typ == 'mietzins' else _KUENDIGUNG_FILLER
    return kt in reg


def fill_anfangsmietzins(vertrag, daten, verwaltung=None, kanton=None):
    """Amtliches Anfangsmietzins-Formular (Art. 270 Abs. 2 OR). Nutzt das
    Original-AcroForm des Kantons, sobald `<KT>_anfangsmietzins_original.pdf`
    hinterlegt und ein Filler registriert ist. Fällt sonst auf das
    kanton-adaptive reportlab-Formular zurück (Schlichtungsbehörden + korrekter
    Kantonsname werden dort ohnehin je Liegenschaft gesetzt)."""
    from core.services.kantone import kanton_fuer_liegenschaft
    kt = (kanton or kanton_fuer_liegenschaft(vertrag.einheit.liegenschaft) or '').upper()
    fn = _ANFANG_FILLER.get(kt)
    pfad = os.path.join(_DIR, f'{kt}_anfangsmietzins_original.pdf')
    if fn and os.path.exists(pfad):
        return fn(vertrag, daten, verwaltung=verwaltung)
    from core.services.amtliche_formulare_so import anfangsmietzins_so_pdf
    return anfangsmietzins_so_pdf(vertrag, daten, verwaltung=verwaltung)


def fill_mietzins(vertrag, daten, verwaltung=None, kanton=None):
    """Füllt das amtliche Mietzins-Formular des passenden Kantons. Gibt None zurück,
    wenn für den Kanton (noch) kein Original hinterlegt ist."""
    from core.services.kantone import kanton_fuer_liegenschaft
    kt = (kanton or kanton_fuer_liegenschaft(vertrag.einheit.liegenschaft) or '').upper()
    fn = _MIETZINS_FILLER.get(kt)
    return fn(vertrag, daten, verwaltung=verwaltung) if fn else None


def fill_kuendigung(vertrag, kuendigung, verwaltung=None, kanton=None, empfaenger=None):
    from core.services.kantone import kanton_fuer_liegenschaft
    kt = (kanton or kanton_fuer_liegenschaft(vertrag.einheit.liegenschaft) or '').upper()
    fn = _KUENDIGUNG_FILLER.get(kt)
    return fn(vertrag, kuendigung, verwaltung=verwaltung, empfaenger=empfaenger) if fn else None


def _kuendigung_render(vertrag, kuendigung, verwaltung=None, empfaenger=None):
    """Rendert die Kündigung — Kantons-Original wenn vorhanden, sonst SO-Nachbildung.
    `empfaenger` (Art. 266n) adressiert die Kopie an genau einen Ehegatten."""
    pdf = fill_kuendigung(vertrag, kuendigung, verwaltung=verwaltung, empfaenger=empfaenger)
    if pdf is None:
        from core.services.amtliche_formulare_so import kuendigung_so_pdf
        pdf = kuendigung_so_pdf(vertrag, kuendigung, verwaltung=verwaltung, empfaenger=empfaenger)
    return pdf


def kuendigung_zustellkopien(vertrag, kuendigung, verwaltung=None):
    """Liste (label, pdf_bytes) der zuzustellenden Kündigungskopien.

    Art. 266n OR: Kündigt der VERMIETER eine Familienwohnung, ist die Kündigung
    dem Mieter UND seinem Ehegatten SEPARAT (je eigene Adresse) zuzustellen —
    sonst ist sie nichtig. Dann zwei individuell adressierte Kopien; sonst eine
    Kopie (Adressblock nennt wie bisher die ganze Mieterschaft)."""
    mieter = vertrag.mieter
    absender = getattr(kuendigung, 'absender', 'mieter')
    hat_ehegatte = bool(vertrag.mitmieter_id or (vertrag.mitmieter_name or '').strip())
    getrennt = (absender == 'vermieter' and vertrag.familienwohnung and hat_ehegatte)
    if not getrennt:
        return [(None, _kuendigung_render(vertrag, kuendigung, verwaltung=verwaltung))]

    haupt = Empfaenger(name=f"{mieter.vorname} {mieter.nachname}".strip(),
                       strasse=mieter.strasse, plz=mieter.plz, ort=mieter.ort)
    if vertrag.mitmieter_id:
        m2 = vertrag.mitmieter
        gatte = Empfaenger(name=m2.display_name, strasse=m2.strasse or mieter.strasse,
                           plz=m2.plz or mieter.plz, ort=m2.ort or mieter.ort)
    else:
        # Ehegatte ohne eigene Adresse → an die (gemeinsame) Wohnadresse zustellen.
        gatte = Empfaenger(name=(vertrag.mitmieter_name or '').strip(),
                           strasse=mieter.strasse, plz=mieter.plz, ort=mieter.ort)
    return [(e.name, _kuendigung_render(vertrag, kuendigung, verwaltung=verwaltung, empfaenger=e))
            for e in (haupt, gatte)]

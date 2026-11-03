"""Nebenkosten-Abrechnung pro Mieter als PDF (Einzel + Sammel).

Nutzt die kanonische Engine core.utils.billing.berechne_abrechnung — dieselben
Zahlen wie Detailansicht und Verbuchung. Erzeugt je Mieter eine transparente
Abrechnung (Kostenpositionen + Verteilschlüssel + Anteil − Akonto = Saldo).
"""
import io
from decimal import Decimal

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

from core.services.dok_layout import DokCanvas
from core.services.dokumentsprache import nur_deutsch
from core.services.druckfarben import EMBER_FLAECHE_RGB
from core.zeit import datum_heute


def _chf(v):
    try:
        return f"{Decimal(v):,.2f}".replace(',', "'")
    except Exception:
        return "0.00"


_SCHLUESSEL_LABEL = {'m2': 'Fläche (m²)', 'm3': 'Volumen (m³)', 'einheit': 'pro Einheit',
                     'personen': 'Personenzahl', 'verbrauch': 'Verbrauch', 'heizung': 'Heizung',
                     'zimmer': 'Zimmerzahl', 'anteil': 'Wertquote', 'prozent': 'Prozentanteil'}


def _draw_page(c, k):
    """Zeichnet eine Mieter-Abrechnung auf die aktuelle Canvas-Seite."""
    w, h = A4
    vw = k.get('verwaltung')
    # Empfänger im Fenster, Ort/Datum, Titel: gemeinsames Briefgerüst (core/services/dok_layout.py)
    ort = (getattr(vw, 'ort', '') or '') if vw else ''
    heute = datum_heute().strftime('%d.%m.%Y')
    y = c.brief(list(k.get('adresse', [])), f"{ort + ', ' if ort else ''}{heute}", "Nebenkostenabrechnung",
                untertitel=f"Abrechnungsperiode: {k.get('periode', '')}")
    c.setFillColorRGB(0.1, 0.1, 0.1)

    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.22, 0.25, 0.32)
    c.drawString(20 * mm, y + 3 * mm, f"Objekt: {k.get('objekt', '')}")
    y -= 4 * mm

    # Kostenpositionen der Liegenschaft (Transparenz)
    c.setFillColorRGB(0.4, 0.45, 0.5)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(20 * mm, y, "KOSTENPOSITION")
    c.drawString(120 * mm, y, "VERTEILUNG")
    c.drawRightString(w - 20 * mm, y, "BETRAG (TOTAL)")
    y -= 3 * mm
    c.setStrokeColorRGB(0.85, 0.87, 0.9)
    c.line(20 * mm, y, w - 20 * mm, y)
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.1, 0.1, 0.1)
    for pos in k.get('positionen', []):
        if y < 60 * mm:
            c.showPage(); y = c.Y_FOLGE
        c.drawString(20 * mm, y, str(pos.get('kategorie') or pos.get('text') or '—')[:52])
        c.setFillColorRGB(0.5, 0.55, 0.6)
        c.drawString(120 * mm, y, _SCHLUESSEL_LABEL.get(pos.get('schluessel'), pos.get('schluessel') or '—'))
        c.setFillColorRGB(0.1, 0.1, 0.1)
        c.drawRightString(w - 20 * mm, y, _chf(pos.get('betrag', 0)))
        y -= 5.5 * mm

    y -= 2 * mm
    c.setStrokeColorRGB(0.85, 0.87, 0.9)
    c.line(20 * mm, y, w - 20 * mm, y)
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.4, 0.45, 0.5)
    c.drawString(20 * mm, y, "Total umlagefähige Kosten der Liegenschaft")
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.drawRightString(w - 20 * mm, y, f"CHF {_chf(k.get('total_kosten', 0))}")

    # Ihr Anteil-Block (zusammenhängend: der Kasten wird nicht über einen Seitenumbruch gerissen)
    y -= 16 * mm
    if y < 82 * mm:
        c.showPage()
        y = c.Y_FOLGE - 4 * mm
    c.setFillColorRGB(*EMBER_FLAECHE_RGB)
    c.rect(20 * mm, y - 26 * mm, w - 40 * mm, 32 * mm, fill=1, stroke=0)
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(24 * mm, y, "Ihre Abrechnung")
    c.setFont("Helvetica", 10)
    y -= 8 * mm
    c.drawString(24 * mm, y, "Ihr Kostenanteil")
    c.drawRightString(w - 24 * mm, y, f"CHF {_chf(k.get('kosten_anteil', 0))}")
    y -= 6 * mm
    c.drawString(24 * mm, y, "− Bezahlte Akontozahlungen")
    c.drawRightString(w - 24 * mm, y, f"CHF {_chf(k.get('akonto', 0))}")
    y -= 3 * mm
    c.setStrokeColor(c.akzent)
    c.line(24 * mm, y, w - 24 * mm, y)
    y -= 6 * mm
    saldo = Decimal(str(k.get('saldo', 0)))
    nachzahlung = k.get('nachzahlung', saldo > 0)
    c.setFont("Helvetica-Bold", 11)
    if nachzahlung:
        c.setFillColorRGB(0.8, 0.1, 0.1)
        c.drawString(24 * mm, y, "Nachzahlung zu Ihren Lasten")
        c.drawRightString(w - 24 * mm, y, f"CHF {_chf(abs(saldo))}")
    else:
        c.setFillColorRGB(0.0, 0.5, 0.25)
        c.drawString(24 * mm, y, "Guthaben zu Ihren Gunsten")
        c.drawRightString(w - 24 * mm, y, f"CHF {_chf(abs(saldo))}")

    # Ihr Anteil nach Kostenart und Anhang (NK-Wizard): Woraus sich der Anteil zusammensetzt,
    # was der Vertrag ausschliesst und wie Leerstand und Heizverbrauch geteilt wurden.
    from portfolio.models import Verteilschluessel
    namen = dict(Verteilschluessel.KOSTENART_CHOICES)
    y -= 14 * mm

    def _platz(y):
        if y < 34 * mm:
            c.showPage()
            return c.Y_FOLGE
        return y

    teile = k.get('aufschluesselung') or []
    if teile:
        c.setFillColorRGB(0.4, 0.45, 0.5)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(20 * mm, y, "IHR ANTEIL NACH KOSTENART")
        y -= 5 * mm
        c.setFont("Helvetica", 9)
        c.setFillColorRGB(0.1, 0.1, 0.1)
        for t in teile:
            y = _platz(y)
            c.drawString(24 * mm, y, str(namen.get(t.get('kostenart'), t.get('kostenart') or '—')))
            c.drawRightString(w - 24 * mm, y, _chf(t.get('betrag', 0)))
            y -= 5 * mm
        y -= 3 * mm
    anhang = list(k.get('anhang') or [])
    if k.get('ausgeschlossen'):
        anhang.append('Nach Mietvertrag nicht von Ihnen getragen: '
                      + ', '.join(str(namen.get(x, x)) for x in k['ausgeschlossen']) + '.')
    if anhang:
        y = _platz(y)
        c.setFillColorRGB(0.4, 0.45, 0.5)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(20 * mm, y, "ANHANG")
        y -= 4.5 * mm
        c.setFont("Helvetica", 8)
        import textwrap
        for text in anhang:
            for zeile in textwrap.wrap(text, 115):
                y = _platz(y)
                c.drawString(20 * mm, y, zeile)
                y -= 4 * mm

    # Rechtsgrundlagen (VMWG / OR) — konsistent zur klassischen Abrechnung
    from core.services.mietrecht import ref as _mr
    y -= 6 * mm
    if y < 32 * mm:
        c.showPage()
        y = c.Y_FOLGE
    c.setFillColorRGB(0.3, 0.33, 0.4)
    c.setFont("Helvetica", 7.5)
    c.drawString(20 * mm, y,
                 f"Umgelegt werden nur die vertraglich vereinbarten Nebenkosten ({_mr('nebenkosten')}, VMWG Art. 4-8) nach dem vereinbarten Verteilschlüssel.")
    c.drawString(20 * mm, y - 4 * mm,
                 "Einsicht in die Originalbelege ist nach Art. 257b Abs. 2 OR nach Terminvereinbarung jederzeit möglich.")
    if nachzahlung:
        c.drawString(20 * mm, y - 8 * mm,
                     "Bitte begleichen Sie die Nachzahlung innert 30 Tagen. Beanstandungen sind innert 30 Tagen schriftlich mitzuteilen.")
    else:
        c.drawString(20 * mm, y - 8 * mm,
                     "Ein allfälliges Guthaben wird Ihnen gutgeschrieben. Beanstandungen sind innert 30 Tagen schriftlich mitzuteilen.")


def _neue_canvas(buf, k, titel):
    """Canvas mit dem Briefkopf der Verwaltung der Abrechnung (`k['verwaltung']`)."""
    return DokCanvas(buf, organisation=k.get('verwaltung'), absender=['Verwaltung', '', ''], titel=titel,
                     ref=(k.get('adresse') or [''])[0])


@nur_deutsch
def generate_nk_pdf_einzeln(kontext):
    """Ein Mieter → einseitige Abrechnung (Bytes)."""
    buf = io.BytesIO()
    c = _neue_canvas(buf, kontext, f"Nebenkostenabrechnung {kontext.get('periode', '')}")
    c.setTitle(f"Nebenkostenabrechnung {kontext.get('periode','')}")
    _draw_page(c, kontext)
    c.showPage()
    c.save()
    return buf.getvalue()


@nur_deutsch
def generate_nk_pdf_sammel(kontext_liste):
    """Mehrere Mieter → ein Sammel-PDF (eine Seite pro Mieter)."""
    buf = io.BytesIO()
    erster = kontext_liste[0] if kontext_liste else {}
    c = _neue_canvas(buf, erster, "Nebenkostenabrechnung")
    c.setTitle("Nebenkostenabrechnungen (Sammel)")
    for nr, k in enumerate(kontext_liste):
        if nr:
            c.neues_dokument()
            c.ref_kopf = (k.get('adresse') or [''])[0]
        _draw_page(c, k)
        c.showPage()
    c.save()
    return buf.getvalue()

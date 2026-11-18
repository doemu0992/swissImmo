"""Portfolio-Report (PDF) für das Eigentümer-Portal: Kennzahlen + Objektliste.

In der Korrespondenzsprache des Eigentümers (D11) — eine Zahlenaufstellung
ohne Rechtstext. Auch die Objekttypen folgen ihr: Die Daten werden deshalb im
selben Sprachblock gelesen (`generate_portfolio_report_fuer`)."""
import io
import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from django.utils.translation import gettext

from core.services.dok_layout import DokCanvas
from core.services.dokumentsprache import in_sprache, sprache_von


def _chf(v):
    try:
        return f"{float(v):,.0f}".replace(',', "'")
    except Exception:
        return '0'


def generate_portfolio_report_fuer(eigentuemer):
    """Daten lesen und Report erzeugen, beides in der Sprache des Eigentümers."""
    from core.views.portal import _portfolio_daten
    with in_sprache(sprache_von(eigentuemer)):
        return _report(eigentuemer, _portfolio_daten(eigentuemer))


def generate_portfolio_report(eigentuemer, daten):
    with in_sprache(sprache_von(eigentuemer)):
        return _report(eigentuemer, daten)


def _report(eigentuemer, daten):
    buf = io.BytesIO()
    c = DokCanvas(buf, organisation=getattr(eigentuemer, 'organisation', None),
                  absender=[eigentuemer.firma_oder_name, '', ''],
                  titel=gettext('Portfolio-Report'), ref=eigentuemer.firma_oder_name)
    w, h = A4
    heute = datetime.date.today().strftime('%d.%m.%Y')

    # Titel unter dem Briefkopf (früher ein Farbband); ab Seite 2 trägt der Seitenkopf ihn
    c.setFillColor(c.akzent)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, c.Y_INHALT, gettext('Portfolio-Report'))
    c.setFillColorRGB(0.22, 0.25, 0.32)
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, c.Y_INHALT - 6 * mm, gettext('%(name)s · Stand %(datum)s') % {'name': eigentuemer.firma_oder_name, 'datum': heute})
    c.setFillColorRGB(0, 0, 0)
    y = c.Y_INHALT - 18 * mm

    # KPI-Block
    kpis = [
        (gettext("Liegenschaften"), str(len(daten['liegenschaften']))),
        (gettext("Einheiten"), str(daten['total_einheiten'])),
        (gettext("Vermietet"), f"{daten['total_vermietet']}/{daten['total_einheiten']}"),
        (gettext("Leerstand"), f"{daten['leerquote']:.1f}%"),
        (gettext("Ist-Miete/Mt."), f"CHF {_chf(daten['total_soll'])}"),
        (gettext("Jahres-Ist"), f"CHF {_chf(daten['jahres_soll'])}"),
    ]
    if daten.get('bruttorendite') is not None:
        kpis.append((gettext("Bruttorendite") + "*", f"{daten['bruttorendite']:.2f}%"))
    else:
        kpis.append((gettext("Bruttorendite") + "*", gettext("nicht berechenbar")))
    col_w = (w - 40 * mm) / 3
    for i, (label, wert) in enumerate(kpis):
        cx = 20 * mm + (i % 3) * col_w
        cy = y - (i // 3) * 20 * mm
        c.setStrokeColorRGB(0.85, 0.87, 0.9)
        c.roundRect(cx, cy - 15 * mm, col_w - 4 * mm, 15 * mm, 3, stroke=1, fill=0)
        c.setFont("Helvetica", 7.5); c.setFillColorRGB(0.4, 0.45, 0.5)
        c.drawString(cx + 4 * mm, cy - 5 * mm, label.upper())
        c.setFont("Helvetica-Bold", 12); c.setFillColorRGB(0.1, 0.12, 0.15)
        c.drawString(cx + 4 * mm, cy - 12 * mm, wert)
    rows_kpi = (len(kpis) + 2) // 3
    y = y - rows_kpi * 20 * mm - 6 * mm

    # Objektliste je Liegenschaft
    c.setFillColorRGB(0, 0, 0)
    for lg in daten['liegenschaften']:
        if y < 50 * mm:
            c.showPage(); y = c.Y_FOLGE
        c.setFont("Helvetica-Bold", 11)
        c.drawString(20 * mm, y, lg['adresse'])
        c.setFont("Helvetica", 9); c.setFillColorRGB(0.3, 0.5, 0.3)
        rendite = (' · ' + (gettext('Rendite %(prozent)s%%') % {'prozent': f"{lg['rendite']:.2f}"}
                            if lg.get('rendite') is not None else gettext('Rendite nicht berechenbar')))
        c.drawRightString(w - 20 * mm, y, gettext('CHF %(betrag)s/Mt.') % {'betrag': _chf(lg['soll_monat'])} + rendite)
        c.setFillColorRGB(0, 0, 0)
        y -= 6 * mm
        c.setFont("Helvetica", 8.5)
        for e in lg['einheiten']:
            if y < 30 * mm:
                c.showPage(); y = c.Y_FOLGE
                c.setFont("Helvetica", 8.5)
            mieter = e['mieter'] or gettext('LEERSTAND')
            zeile = f"  {e['bezeichnung']} · {e['typ']}"
            c.drawString(22 * mm, y, zeile[:60])
            c.drawString(105 * mm, y, mieter[:32])
            if e['brutto']:
                c.drawRightString(w - 20 * mm, y, f"CHF {_chf(e['brutto'])}")
            else:
                c.setFillColorRGB(0.8, 0.15, 0.15)
                c.drawRightString(w - 20 * mm, y, gettext('leer'))
                c.setFillColorRGB(0, 0, 0)
            y -= 5 * mm
        y -= 4 * mm

    # Fussnote
    if y < 32 * mm:
        c.showPage(); y = c.Y_FOLGE
    c.setFont("Helvetica-Oblique", 7); c.setFillColorRGB(0.3, 0.3, 0.3)
    c.drawString(20 * mm, y,
                 "* " + gettext("Bruttorendite = Netto-Sollmietzins (ohne Nebenkosten) / Verkehrswert, ersatzweise Anlagekosten. Ohne hinterlegten Wert keine Rendite."))
    if daten.get('rendite_ohne_wert'):
        y -= 4 * mm
        c.drawString(20 * mm, y, gettext("Liegenschaften ohne hinterlegten Wert (nicht in der Rendite): %(n)s") % {'n': daten['rendite_ohne_wert']})

    c.save(); buf.seek(0)
    return buf.read()

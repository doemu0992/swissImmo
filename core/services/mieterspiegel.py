"""Mieterspiegel (Rent Roll): je Liegenschaft alle Einheiten mit Mieter,
Mietzins (netto/NK/brutto) und Vertragsdaten sowie Soll-/Ist-/Leerstand-Summen.
Das zentrale Bewirtschaftungs-Dokument für Eigentümer und Verwaltung."""
from decimal import Decimal


def berechne_mieterspiegel(liegenschaften):
    """Gibt je Liegenschaft ein dict {lg, zeilen, totals} zurück."""
    from portfolio.models import Einheit
    from rentals.models import Mietvertrag
    from django.db.models import Q

    result = []
    for lg in liegenschaften:
        einheiten = Einheit.objects.filter(liegenschaft=lg).order_by('bezeichnung')
        # Aktive Verträge der Liegenschaft (als Haupt- oder Nebenobjekt) einsammeln
        vertraege = (Mietvertrag.objects.filter(status='aktiv')
                     .filter(Q(einheit__liegenschaft=lg) | Q(nebenobjekte__liegenschaft=lg))
                     .select_related('mieter', 'einheit').distinct())
        belegt = {}   # einheit_id -> vertrag
        for v in vertraege:
            if v.einheit_id:
                belegt.setdefault(v.einheit_id, v)
            for ne in v.nebenobjekte.all():
                belegt.setdefault(ne.id, v)

        zeilen = []
        soll_netto = soll_nk = ist_netto = ist_nk = leer_fr = Decimal('0.00')
        leer_n = 0
        for e in einheiten:
            netto = e.nettomiete_aktuell or Decimal('0.00')
            nk = e.nebenkosten_aktuell or Decimal('0.00')
            soll_netto += netto
            soll_nk += nk
            v = belegt.get(e.id)
            if v:
                ist_netto += netto
                ist_nk += nk
                zeilen.append({
                    'einheit': e, 'bezeichnung': e.bezeichnung, 'typ': e.get_typ_display(),
                    'flaeche': e.flaeche_m2, 'zimmer': e.zimmer,
                    'belegt': True, 'mieter': v.mieter.display_name if v.mieter_id else '—',
                    'netto': netto, 'nk': nk, 'brutto': netto + nk,
                    'beginn': v.beginn, 'ende': v.ende,
                })
            else:
                leer_n += 1
                leer_fr += netto + nk
                zeilen.append({
                    'einheit': e, 'bezeichnung': e.bezeichnung, 'typ': e.get_typ_display(),
                    'flaeche': e.flaeche_m2, 'zimmer': e.zimmer,
                    'belegt': False, 'mieter': None,
                    'netto': netto, 'nk': nk, 'brutto': netto + nk,
                    'beginn': None, 'ende': None,
                })
        anzahl = len(zeilen)
        totals = {
            'anzahl': anzahl, 'belegt': anzahl - leer_n, 'leer': leer_n,
            'soll_netto': soll_netto, 'soll_nk': soll_nk, 'soll_brutto': soll_netto + soll_nk,
            'ist_netto': ist_netto, 'ist_nk': ist_nk, 'ist_brutto': ist_netto + ist_nk,
            'leer_fr': leer_fr,
            'leerstandsquote': round(leer_n / anzahl * 100, 1) if anzahl else 0.0,
        }
        result.append({'lg': lg, 'zeilen': zeilen, 'totals': totals})
    return result


def _fmt(d):
    try:
        return f"{Decimal(str(d)):,.2f}".replace(",", "'")
    except Exception:
        return str(d)


def generate_mieterspiegel_pdf(spiegel, verwaltung=None, stichtag=None):
    import io
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    from reportlab.lib import colors

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    w, h = landscape(A4)
    c.setTitle("Mieterspiegel")
    indigo = colors.HexColor("#4F46E5")

    def kopf(lg):
        c.setFillColor(indigo)
        c.rect(0, h - 20 * mm, w, 20 * mm, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(15 * mm, h - 13 * mm, f"Mieterspiegel — {lg.strasse}, {lg.plz} {lg.ort}")
        c.setFont("Helvetica", 8)
        if verwaltung:
            c.drawRightString(w - 15 * mm, h - 9 * mm, verwaltung.firma or "")
        if stichtag:
            c.drawRightString(w - 15 * mm, h - 15 * mm, f"Stichtag {stichtag:%d.%m.%Y}")
        c.setFillColor(colors.black)

    cols = [
        ("Einheit", 15), ("Typ", 55), ("m²", 82), ("Mieter", 98),
        ("Netto", 170), ("NK", 195), ("Brutto", 222), ("Beginn", 250), ("Ende", 272),
    ]

    def spaltenkopf(y):
        c.setFont("Helvetica-Bold", 7.5); c.setFillColor(colors.HexColor("#64748B"))
        for label, x in cols:
            if label in ("Netto", "NK", "Brutto"):
                c.drawRightString((x + 20) * mm, y, label)
            else:
                c.drawString(x * mm, y, label)
        c.setFillColor(colors.black)
        c.setStrokeColor(colors.HexColor("#CBD5E1"))
        c.line(15 * mm, y - 1.5 * mm, w - 15 * mm, y - 1.5 * mm)

    for block in spiegel:
        lg = block['lg']
        kopf(lg)
        y = h - 28 * mm
        spaltenkopf(y)
        y -= 6 * mm
        c.setFont("Helvetica", 8)
        for z in block['zeilen']:
            if y < 25 * mm:
                c.showPage(); kopf(lg); y = h - 28 * mm; spaltenkopf(y); y -= 6 * mm; c.setFont("Helvetica", 8)
            if not z['belegt']:
                c.setFillColor(colors.HexColor("#B45309"))
            c.drawString(15 * mm, y, str(z['bezeichnung'])[:16])
            c.drawString(55 * mm, y, str(z['typ'])[:12])
            c.drawString(82 * mm, y, _fmt(z['flaeche']) if z['flaeche'] else '—')
            c.drawString(98 * mm, y, (z['mieter'] or 'LEERSTAND')[:34])
            c.drawRightString(190 * mm, y, _fmt(z['netto']))
            c.drawRightString(215 * mm, y, _fmt(z['nk']))
            c.drawRightString(242 * mm, y, _fmt(z['brutto']))
            c.drawString(250 * mm, y, z['beginn'].strftime('%d.%m.%y') if z['beginn'] else '')
            c.drawString(272 * mm, y, z['ende'].strftime('%d.%m.%y') if z['ende'] else '')
            c.setFillColor(colors.black)
            y -= 5 * mm

        t = block['totals']
        y -= 1 * mm
        c.setStrokeColor(colors.HexColor("#334155")); c.setLineWidth(0.8)
        c.line(15 * mm, y, w - 15 * mm, y)
        y -= 6 * mm
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(15 * mm, y, f"Total {t['anzahl']} Einheiten · {t['belegt']} belegt · {t['leer']} leer ({t['leerstandsquote']}%)")
        c.drawRightString(190 * mm, y, _fmt(t['soll_netto']))
        c.drawRightString(215 * mm, y, _fmt(t['soll_nk']))
        c.drawRightString(242 * mm, y, _fmt(t['soll_brutto']))
        y -= 5 * mm
        c.setFont("Helvetica", 8); c.setFillColor(colors.HexColor("#64748B"))
        c.drawString(15 * mm, y, f"Ist-Mietzins (belegt): CHF {_fmt(t['ist_brutto'])}/Mt.  ·  Ausfall Leerstand: CHF {_fmt(t['leer_fr'])}/Mt.")
        c.setFillColor(colors.black)
        c.showPage()

    if not spiegel:
        kopf_leer = c
        c.setFont("Helvetica", 11)
        c.drawString(20 * mm, h - 40 * mm, "Keine Liegenschaften.")
        c.showPage()
    c.save(); buf.seek(0)
    return buf.read()

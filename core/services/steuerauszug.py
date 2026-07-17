"""Steuerauszug / Liegenschaftsrechnung für Eigentümer (pro Jahr).

Vereinfachte Erfolgsrechnung je Liegenschaft:
  Ist-Mieterträge  −  Ausgaben (Kreditoren)  −  Abschreibungen (AfA)  =  Netto.
Read-only aus den bestehenden Finanzdaten. Ersetzt keine Steuerberatung.
"""
import io
from decimal import Decimal


def _chf(v):
    try:
        return f"{Decimal(v):,.2f}".replace(',', "'")
    except Exception:
        return "0.00"


def steuerauszug_daten(mandant, jahr):
    """Aggregiert Erträge/Ausgaben/AfA/Honorar je Liegenschaft des Mandanten für ein Jahr."""
    from finance.models import Zahlungseingang, KreditorenRechnung, Abschreibung
    lgs = list(mandant.liegenschaften.all().order_by('strasse'))
    lg_ids = [l.id for l in lgs]
    per = {l.id: {'ertrag': Decimal('0'), 'ausgaben': Decimal('0'), 'afa': Decimal('0'),
                  'honorar': Decimal('0')} for l in lgs}

    # 1) Ist-Mieterträge (verbuchte Zahlungseingänge im Jahr)
    zes = (Zahlungseingang.objects.filter(status='verbucht', datum_eingang__year=jahr)
           .select_related('vertrag__einheit'))
    for z in zes:
        lid = None
        if z.vertrag_id and z.vertrag and z.vertrag.einheit_id:
            lid = z.vertrag.einheit.liegenschaft_id
        if lid not in per:
            lid = z.liegenschaft_id
        if lid in per:
            per[lid]['ertrag'] += z.betrag or Decimal('0')

    # 2) Ausgaben (Kreditorenrechnungen, ohne Stornos)
    krs = (KreditorenRechnung.objects.filter(liegenschaft_id__in=lg_ids, datum__year=jahr)
           .exclude(status='storniert'))
    for k in krs:
        if k.liegenschaft_id in per:
            per[k.liegenschaft_id]['ausgaben'] += k.betrag or Decimal('0')

    # 3) Abschreibungen (AfA) des Jahres
    afas = (Abschreibung.objects.filter(jahr=jahr, anlage__liegenschaft_id__in=lg_ids)
            .select_related('anlage'))
    for a in afas:
        lid = a.anlage.liegenschaft_id
        if lid in per:
            per[lid]['afa'] += a.betrag or Decimal('0')

    # 4) Verwaltungshonorar (Konto 4500) — wird direkt gebucht (Soll 4500/Haben
    # Bank), nie als Kreditorenrechnung, und fehlte deshalb in den Ausgaben.
    # Netto Soll−Haben je Liegenschaft: Stornos heben sich damit von selbst auf.
    from finance.models import Buchung, Buchungskonto
    from django.db.models import Q
    k4500 = Buchungskonto.objects.filter(nummer='4500').first()
    if k4500:
        hqs = (Buchung.objects
               .filter(liegenschaft_id__in=lg_ids, datum__year=jahr)
               .filter(Q(soll_konto=k4500) | Q(haben_konto=k4500)))
        for b in hqs:
            if b.liegenschaft_id not in per:
                continue
            if b.soll_konto_id == k4500.id:
                per[b.liegenschaft_id]['honorar'] += b.betrag or Decimal('0')
            if b.haben_konto_id == k4500.id:
                per[b.liegenschaft_id]['honorar'] -= b.betrag or Decimal('0')

    zeilen = []
    tot = {'ertrag': Decimal('0'), 'ausgaben': Decimal('0'), 'afa': Decimal('0'),
           'honorar': Decimal('0'), 'netto': Decimal('0')}
    for l in lgs:
        d = per[l.id]
        netto = d['ertrag'] - d['ausgaben'] - d['afa'] - d['honorar']
        zeilen.append({'lg': l, **d, 'netto': netto})
        for k in ('ertrag', 'ausgaben', 'afa', 'honorar'):
            tot[k] += d[k]
        tot['netto'] += netto
    return {'jahr': jahr, 'zeilen': zeilen, 'total': tot,
            'mandant': mandant.firma_oder_name if mandant else ''}


def generate_steuerauszug_pdf(mandant, jahr):
    """Erzeugt den Steuerauszug als PDF (Bytes)."""
    from reportlab.pdfgen import canvas as _canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm

    daten = steuerauszug_daten(mandant, jahr)
    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    c.setTitle(f"Steuerauszug {jahr}")

    c.setFillColorRGB(0.26, 0.22, 0.79)
    c.rect(0, h - 30 * mm, w, 30 * mm, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, h - 15 * mm, f"Steuerauszug {jahr}")
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, h - 23 * mm, f"{daten['mandant']} · Liegenschaftsrechnung (vereinfacht)")

    c.setFillColorRGB(0.1, 0.1, 0.1)
    y = h - 42 * mm
    # Tabellenkopf
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColorRGB(0.4, 0.45, 0.5)
    c.drawString(20 * mm, y, "LIEGENSCHAFT")
    c.drawRightString(w - 62 * mm, y, "MIETERTRÄGE")
    c.drawRightString(w - 40 * mm, y, "AUSGABEN")
    c.drawRightString(w - 20 * mm, y, "AfA / NETTO")
    y -= 3 * mm
    c.setStrokeColorRGB(0.85, 0.87, 0.9)
    c.line(20 * mm, y, w - 20 * mm, y)
    y -= 7 * mm

    c.setFont("Helvetica", 9)
    for z in daten['zeilen']:
        if y < 40 * mm:
            c.showPage(); y = h - 25 * mm
        lg = z['lg']
        c.setFillColorRGB(0.1, 0.1, 0.1)
        c.drawString(20 * mm, y, f"{lg.strasse}, {lg.plz} {lg.ort}"[:48])
        c.drawRightString(w - 62 * mm, y, _chf(z['ertrag']))
        c.drawRightString(w - 40 * mm, y, _chf(z['ausgaben']))
        c.setFillColorRGB(0.5, 0.55, 0.6)
        c.drawRightString(w - 20 * mm, y, f"AfA {_chf(z['afa'])}")
        y -= 4.5 * mm
        if z['honorar']:
            c.setFillColorRGB(0.5, 0.55, 0.6)
            c.drawRightString(w - 40 * mm, y, f"Verwaltungshonorar {_chf(z['honorar'])}")
        c.setFillColorRGB(0.0, 0.5, 0.25) if z['netto'] >= 0 else c.setFillColorRGB(0.8, 0.1, 0.1)
        c.setFont("Helvetica-Bold", 9)
        c.drawRightString(w - 20 * mm, y, f"Netto CHF {_chf(z['netto'])}")
        c.setFont("Helvetica", 9)
        y -= 8 * mm

    # Total
    t = daten['total']
    y -= 2 * mm
    c.setStrokeColorRGB(0.26, 0.22, 0.79)
    c.line(20 * mm, y, w - 20 * mm, y)
    y -= 7 * mm
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "TOTAL PORTFOLIO")
    c.drawRightString(w - 62 * mm, y, _chf(t['ertrag']))
    c.drawRightString(w - 40 * mm, y, _chf(t['ausgaben']))
    c.drawRightString(w - 20 * mm, y, f"Netto CHF {_chf(t['netto'])}")
    if t['honorar']:
        y -= 5 * mm
        c.setFont("Helvetica", 8.5)
        c.setFillColorRGB(0.4, 0.45, 0.5)
        c.drawString(20 * mm, y, "davon Verwaltungshonorar (Konto 4500, im Netto berücksichtigt)")
        c.drawRightString(w - 40 * mm, y, _chf(t['honorar']))

    y -= 16 * mm
    c.setFont("Helvetica", 7.5)
    c.setFillColorRGB(0.5, 0.55, 0.6)
    c.drawString(20 * mm, y, "Mieterträge = verbuchte Zahlungseingänge (Ist). Ausgaben = erfasste Kreditorenrechnungen + Verwaltungshonorar (Konto 4500).")
    c.drawString(20 * mm, y - 4 * mm, "AfA = gebuchte Abschreibungen des Jahres. Vereinfachte Aufstellung — keine Steuerberatung.")

    c.showPage()
    c.save()
    return buf.getvalue()

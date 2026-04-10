# finance/services.py
from portfolio.models import Liegenschaft
from finance.models import AbrechnungsPeriode
from decimal import Decimal
from django.db.models import Sum, Q

def berechne_abrechnung(periode_id):
    """
    Professionelle NK-Abrechnung.
    Zieht alle Belege zusammen und verteilt sie nach Verteilschlüssel
    auf die Mieter und den Leerstand.
    """
    try:
        periode = AbrechnungsPeriode.objects.get(pk=periode_id)
    except AbrechnungsPeriode.DoesNotExist:
        return {'error': 'Periode nicht gefunden'}

    liegenschaft = periode.liegenschaft
    start_p = periode.start_datum
    ende_p = periode.ende_datum
    tage_periode = Decimal((ende_p - start_p).days + 1)

    if tage_periode <= 0:
        return {'error': 'Ungültige Periodendauer (Ende vor Start).'}

    # ---------------------------------------------------------
    # 1. KOSTEN NACH VERTEILSCHLÜSSEL TRENNEN
    # ---------------------------------------------------------
    belege = periode.belege.all()

    total_kosten_m2 = Decimal('0.00')
    total_kosten_einheit = Decimal('0.00')

    kategorien_liste = []

    for beleg in belege:
        # WICHTIGER FIX: Wenn Betrag leer ist (noch nicht gescannt), nimm 0.00
        betrag = beleg.betrag if beleg.betrag is not None else Decimal('0.00')
        art = beleg.verteilschluessel # z.B. 'm2', 'einheit'

        # Nur anzeigen, wenn Betrag > 0
        if betrag > 0:
            kategorien_liste.append({
                'datum': beleg.datum,
                'text': beleg.text,
                'kategorie': beleg.get_kategorie_display(),
                'betrag': betrag,
                'schluessel': art
            })

        if art == 'einheit':
            total_kosten_einheit += betrag
        else:
            # Default ist immer m2
            total_kosten_m2 += betrag

    total_kosten_gesamt = total_kosten_m2 + total_kosten_einheit

    # ---------------------------------------------------------
    # 2. GESAMT-BASIS ERMITTELN
    # ---------------------------------------------------------
    total_flaeche_liegenschaft = liegenschaft.einheiten.aggregate(Sum('flaeche_m2'))['flaeche_m2__sum'] or Decimal('0.00')
    total_anzahl_einheiten = liegenschaft.einheiten.count()

    # Warnung nur wenn wir auch wirklich Kosten haben
    if total_flaeche_liegenschaft == 0 and total_kosten_m2 > 0:
        return {'error': 'Fehler: Kosten nach Fläche vorhanden, aber Gesamtfläche der Liegenschaft ist 0.'}

    # ---------------------------------------------------------
    # 3. BERECHNUNG PRO EINHEIT
    # ---------------------------------------------------------
    abrechnungen = []
    kontroll_summe = Decimal('0.00')

    for einheit in liegenschaft.einheiten.all():
        # A. KOSTENANTEIL DER WOHNUNG BERECHNEN
        anteil_m2 = Decimal('0.00')
        anteil_einheit = Decimal('0.00')

        if total_flaeche_liegenschaft > 0 and einheit.flaeche_m2:
            faktor = einheit.flaeche_m2 / total_flaeche_liegenschaft
            anteil_m2 = total_kosten_m2 * faktor

        if total_anzahl_einheiten > 0:
            anteil_einheit = total_kosten_einheit / Decimal(total_anzahl_einheiten)

        kosten_wohnung_total = anteil_m2 + anteil_einheit

        # B. MIETER ERMITTELN
        vertraege = einheit.vertraege.filter(
            Q(beginn__lte=ende_p) & (Q(ende__isnull=True) | Q(ende__gte=start_p))
        )

        tage_vermietet_total = 0

        for vertrag in vertraege.distinct():
            v_start = max(vertrag.beginn, start_p)
            v_ende = min(vertrag.ende, ende_p) if vertrag.ende else ende_p

            tage_bewohnt = (v_ende - v_start).days + 1
            if tage_bewohnt <= 0: continue

            tage_vermietet_total += tage_bewohnt

            zeit_faktor = Decimal(tage_bewohnt) / tage_periode
            mieter_kosten_anteil = kosten_wohnung_total * zeit_faktor

            # Akonto
            nk_monat = vertrag.nebenkosten or Decimal('0.00')
            akonto_pro_tag = (nk_monat * 12) / 365
            bezahltes_akonto = akonto_pro_tag * Decimal(tage_bewohnt)

            saldo = bezahltes_akonto - mieter_kosten_anteil
            kontroll_summe += mieter_kosten_anteil

            abrechnungen.append({
                'typ': 'mieter',
                'name': f"{vertrag.mieter.vorname} {vertrag.mieter.nachname}",
                'einheit': einheit.bezeichnung,
                'von': v_start,
                'bis': v_ende,
                'tage': tage_bewohnt,
                'kosten_anteil': round(mieter_kosten_anteil, 2),
                'akonto': round(bezahltes_akonto, 2),
                'saldo': round(saldo, 2),
                'nachzahlung': saldo < 0
            })

        # C. LEERSTAND
        tage_leer = int(tage_periode) - tage_vermietet_total

        if tage_leer > 0 and kosten_wohnung_total > 0:
            zeit_faktor_leer = Decimal(tage_leer) / tage_periode
            leerstand_kosten = kosten_wohnung_total * zeit_faktor_leer
            kontroll_summe += leerstand_kosten

            abrechnungen.append({
                'typ': 'leerstand',
                'name': 'Leerstand (Eigentümer)',
                'einheit': einheit.bezeichnung,
                'von': '-',
                'bis': '-',
                'tage': tage_leer,
                'kosten_anteil': round(leerstand_kosten, 2),
                'akonto': Decimal('0.00'),
                'saldo': round(-leerstand_kosten, 2),
                'nachzahlung': True
            })

    abrechnungen.sort(key=lambda x: x['einheit'])

    return {
        'total_kosten': total_kosten_gesamt,
        'total_flaeche': total_flaeche_liegenschaft,
        'belege_details': kategorien_liste,
        'abrechnungen': abrechnungen,
        'kontroll_summe': round(kontroll_summe, 2),
        'differenz': round(total_kosten_gesamt - kontroll_summe, 2)
    }
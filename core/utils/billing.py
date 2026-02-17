import datetime
from decimal import Decimal
from django.db.models import Sum
from core.models import AbrechnungsPeriode, Einheit, Mietvertrag, NebenkostenBeleg

def berechne_abrechnung(periode_id):
    """
    Berechnet die Nebenkostenverteilung für eine Abrechnungsperiode.
    Verteilschlüssel: Wohnfläche (m2) und Zeitdauer (Tage).
    """
    try:
        periode = AbrechnungsPeriode.objects.get(pk=periode_id)
    except AbrechnungsPeriode.DoesNotExist:
        return {'error': 'Periode nicht gefunden'}

    liegenschaft = periode.liegenschaft

    # 1. Alle Kosten summieren
    alle_belege = periode.belege.all()
    total_kosten = alle_belege.aggregate(Sum('betrag'))['betrag__sum'] or Decimal('0.00')

    # Kosten nach Kategorie gruppieren (für spätere Details)
    kategorien_summen = {}
    for beleg in alle_belege:
        kat = beleg.get_kategorie_display()
        kategorien_summen[kat] = kategorien_summen.get(kat, Decimal('0.00')) + beleg.betrag

    # 2. Gesamtfläche ermitteln (Verteilschlüssel)
    total_flaeche = liegenschaft.einheiten.aggregate(Sum('flaeche_m2'))['flaeche_m2__sum'] or Decimal('0.00')

    if total_flaeche == 0:
        return {'error': 'Gesamtfläche der Liegenschaft ist 0 m². Bitte Flächen in Einheiten eintragen.'}

    # 3. Berechnung pro Einheit & Mieter
    abrechnungen = []

    for einheit in liegenschaft.einheiten.all():
        # A. Anteil der Einheit an den Gesamtkosten (nach Fläche)
        if not einheit.flaeche_m2:
            continue # Einheit ohne Fläche überspringen

        anteil_faktor_flaeche = einheit.flaeche_m2 / total_flaeche
        kosten_anteil_einheit = total_kosten * anteil_faktor_flaeche

        # B. Mieter finden, die in dieser Periode da waren
        # (Überschneidung von Vertragsdauer und Abrechnungsperiode)
        vertraege = einheit.vertraege.filter(
            beginn__lte=periode.ende_datum
        ).filter(
            ende__isnull=True
        ) | einheit.vertraege.filter(
            beginn__lte=periode.ende_datum,
            ende__gte=periode.start_datum
        )

        for vertrag in vertraege.distinct():
            # C. Zeitdauer berechnen
            start_relevant = max(vertrag.beginn, periode.start_datum)
            if vertrag.ende:
                ende_relevant = min(vertrag.ende, periode.ende_datum)
            else:
                ende_relevant = periode.ende_datum

            tage_bewohnt = (ende_relevant - start_relevant).days + 1
            tage_periode = (periode.ende_datum - periode.start_datum).days + 1

            if tage_bewohnt <= 0: continue

            zeit_faktor = Decimal(tage_bewohnt) / Decimal(tage_periode)

            # D. Effektive Kosten für diesen Mieter
            mieter_kosten_anteil = kosten_anteil_einheit * zeit_faktor

            # E. Bezahltes Akonto (Monatliches NK * 12 * Zeitfaktor)
            monatliches_akonto = vertrag.nebenkosten or Decimal('0.00')
            jahres_akonto_soll = monatliches_akonto * 12
            bezahltes_akonto = jahres_akonto_soll * zeit_faktor

            # F. Saldo (Negativ = Nachzahlung, Positiv = Guthaben)
            saldo = bezahltes_akonto - mieter_kosten_anteil

            abrechnungen.append({
                'mieter': f"{vertrag.mieter.vorname} {vertrag.mieter.nachname}",
                'einheit': einheit.bezeichnung,
                'tage': tage_bewohnt,
                'anteil_m2': round(einheit.flaeche_m2, 1),
                'kosten_anteil': round(mieter_kosten_anteil, 2),
                'akonto_bezahlt': round(bezahltes_akonto, 2),
                'saldo': round(saldo, 2),
                'nachzahlung': saldo < 0 # True wenn Mieter Geld schuldet
            })

    return {
        'total_kosten': total_kosten,
        'total_flaeche': total_flaeche,
        'kategorien': kategorien_summen,
        'abrechnungen': abrechnungen,
    }
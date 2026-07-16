# core/utils/billing.py
import datetime
import calendar
from decimal import Decimal
from django.db.models import Sum, Q

from portfolio.models import Liegenschaft, Einheit
from rentals.models import Mietvertrag
from finance.models import AbrechnungsPeriode, KreditorenRechnung, Zahlungseingang

def get_heizgradtage_fuer_zeitraum(start_datum, ende_datum):
    """
    Berechnet die Summe der Heizgradtage (HGT) für eine bestimmte Zeitspanne.
    Standard HGT in der Schweiz pro Monat in %:
    Jan:21, Feb:18, Mär:15, Apr:10, Mai:5, Jun:0, Jul:0, Aug:0, Sep:3, Okt:8, Nov:10, Dez:10
    """
    hgt_verteilung = {1: 21, 2: 18, 3: 15, 4: 10, 5: 5, 6: 0, 7: 0, 8: 0, 9: 3, 10: 8, 11: 10, 12: 10}
    total_prozent = Decimal('0')

    curr = start_datum
    while curr <= ende_datum:
        _, tage_im_monat = calendar.monthrange(curr.year, curr.month)
        # Anteiliger Prozentsatz für diesen einen Tag
        tages_prozent = Decimal(hgt_verteilung[curr.month]) / Decimal(tage_im_monat)
        total_prozent += tages_prozent
        curr += datetime.timedelta(days=1)

    return total_prozent / Decimal('100')


def _heiz_verbrauch_pro_einheit(liegenschaft, start_p, ende_p):
    """Verbrauch (Zählerdifferenz) pro Einheit für Heizungs-/Wärmezähler im Zeitraum.
    Gibt {einheit_id: verbrauch} zurück; leer, wenn keine verwertbaren Zählerstände existieren."""
    from portfolio.models import Zaehler, ZaehlerStand
    result = {}
    heiz_typen = ('heiz', 'wärme', 'waerme', 'wmz', 'energie', 'wärmemenge')
    for z in Zaehler.objects.filter(einheit__liegenschaft=liegenschaft):
        typ = (z.typ or '').lower()
        if not any(t in typ for t in heiz_typen):
            continue
        staende = list(ZaehlerStand.objects.filter(
            zaehler=z, datum__gte=start_p, datum__lte=ende_p).order_by('datum'))
        if len(staende) >= 2:
            verbrauch = (staende[-1].wert or Decimal('0')) - (staende[0].wert or Decimal('0'))
            if verbrauch > 0:
                result[z.einheit_id] = result.get(z.einheit_id, Decimal('0')) + verbrauch
    return result


def berechne_abrechnung(periode_id):
    """
    Professionelle Schweizer HNK-Abrechnung (Expert-Version).
    Beinhaltet: Shift-Left (Kreditoren), Heizgradtage, Bestandesrechnung Öl, Pauschal vs. Akonto.
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

    # Totale Heizgradtage der Periode berechnen
    periode_hgt = get_heizgradtage_fuer_zeitraum(start_p, ende_p)
    if periode_hgt <= 0: periode_hgt = Decimal('1') # Fallback zero-division

    # ---------------------------------------------------------
    # 1. KOSTEN SAMMELN (Das Shift-Left Prinzip)
    # ---------------------------------------------------------
    pool_heizkosten = Decimal('0.00')   # Wird nach m3 und HGT verteilt
    pool_nk_m2 = Decimal('0.00')        # Wird nach m2 und Tagen verteilt
    pool_nk_einheit = Decimal('0.00')   # Wird nach Einheit und Tagen verteilt

    kategorien_liste = []

    # A) Manuelle Belege (NebenkostenBeleg)
    for beleg in periode.belege.all():
        betrag = beleg.betrag or Decimal('0.00')
        if betrag <= 0: continue

        if beleg.kategorie == 'heizung' or beleg.verteilschluessel == 'm3':
            pool_heizkosten += betrag
        elif beleg.verteilschluessel == 'einheit':
            pool_nk_einheit += betrag
        else:
            pool_nk_m2 += betrag

        kategorien_liste.append({
            'datum': beleg.datum, 'text': beleg.text, 'kategorie': beleg.get_kategorie_display(),
            'betrag': betrag, 'schluessel': beleg.verteilschluessel, 'quelle': 'Beleg'
        })

    # B) Kreditoren aus Finanzmodul einlesen (Die Automatisierung)
    kreditoren = KreditorenRechnung.objects.filter(
        liegenschaft=liegenschaft,
        is_hnk_relevant=True,
        status__in=['freigegeben', 'bezahlt']
    ).filter(
        Q(leistungs_von__lte=ende_p) & Q(leistungs_bis__gte=start_p) |
        Q(leistungs_von__isnull=True, datum__range=[start_p, ende_p])
    )

    zukauf_oel_l = Decimal('0.00')
    zukauf_oel_chf = Decimal('0.00')

    def _hnk_teile(kred):
        """Split-aware: die tatsächlich HNK-relevanten Kostenteile einer Rechnung.
        Mit Kostenaufteilung nur die HNK-Positionen (Betrag + eigenes Konto), sonst
        die ganze Rechnung. So fliesst z.B. bei einer 300er-Rechnung mit nur 100 HNK
        auch nur 100 in die Nebenkostenabrechnung — nicht mehr der volle Betrag."""
        if kred.hat_positionen:
            return [(p.betrag or Decimal('0.00'), p.konto,
                     f"{kred.lieferant} ({p.konto.bezeichnung}{f' · {p.bezeichnung}' if p.bezeichnung else ''})")
                    for p in kred.positionen.filter(is_hnk_relevant=True)]
        return [(kred.betrag or Decimal('0.00'), kred.konto,
                 f"{kred.lieferant} ({kred.konto.bezeichnung if kred.konto else 'Kreditor'})")]

    for kred in kreditoren:
        # Bestandes-Zukäufe (Öl/Gas) sammeln — auf Rechnungsebene (Menge am Kopf).
        if kred.menge_liter and kred.menge_liter > 0:
            betrag = kred.betrag or Decimal('0.00')
            if betrag <= 0: continue
            zukauf_oel_l += kred.menge_liter
            zukauf_oel_chf += betrag
            kategorien_liste.append({
                'datum': kred.datum, 'text': f"{kred.lieferant} (Öl-Einkauf {kred.menge_liter}L)",
                'kategorie': 'Öl-Einkauf (Bestand)', 'betrag': betrag, 'schluessel': 'm3', 'quelle': 'FiBu'
            })
            continue # Wird in Schritt C abgerechnet

        # Direkte Kosten zuweisen — pro HNK-Teil (Split-aware)
        for betrag, konto, text in _hnk_teile(kred):
            if betrag <= 0: continue
            v_key = konto.standard_verteilschluessel if konto and konto.standard_verteilschluessel else 'm2'
            if konto and ('heiz' in konto.bezeichnung.lower() or 'wärme' in konto.bezeichnung.lower()):
                pool_heizkosten += betrag
                v_key = 'm3'
            elif v_key == 'einheit':
                pool_nk_einheit += betrag
            elif v_key == 'm3':
                pool_heizkosten += betrag
            else:
                pool_nk_m2 += betrag
            kategorien_liste.append({
                'datum': kred.datum, 'text': text,
                'kategorie': 'Kreditor', 'betrag': betrag, 'schluessel': v_key, 'quelle': 'FiBu'
            })

    # C) Bestandesrechnung Heizöl (Gewogener Durchschnittspreis)
    anfangs_l = periode.anfangsbestand_liter or Decimal('0.00')
    anfangs_chf = periode.anfangsbestand_chf or Decimal('0.00')
    end_l = periode.endbestand_liter or Decimal('0.00')

    if anfangs_l > 0 or zukauf_oel_l > 0:
        total_l = anfangs_l + zukauf_oel_l
        total_chf = anfangs_chf + zukauf_oel_chf
        durchschnittspreis = total_chf / total_l if total_l > 0 else Decimal('0')

        end_chf = end_l * durchschnittspreis
        effektive_oel_kosten = total_chf - end_chf

        if effektive_oel_kosten > 0:
            pool_heizkosten += effektive_oel_kosten
            kategorien_liste.append({
                'datum': ende_p, 'text': "Effektiver Heizöl-Verbrauch (Anfang + Zukauf - Endbestand)",
                'kategorie': 'Heizmaterial', 'betrag': round(effektive_oel_kosten, 2), 'schluessel': 'm3', 'quelle': 'Bestand'
            })

    # D) Verwaltungshonorar (Standardmässig 3% auf die Nebenkosten)
    subtotal = pool_heizkosten + pool_nk_m2 + pool_nk_einheit
    honorarsatz = Decimal('0.03')
    honorar_betrag = subtotal * honorarsatz
    pool_nk_m2 += honorar_betrag

    kategorien_liste.append({
        'datum': ende_p, 'text': "Verwaltungshonorar (3%)",
        'kategorie': 'Verwaltung', 'betrag': round(honorar_betrag, 2), 'schluessel': 'm2', 'quelle': 'System'
    })

    total_kosten_gesamt = pool_heizkosten + pool_nk_m2 + pool_nk_einheit

    # ---------------------------------------------------------
    # 2. GESAMT-BASIS DER LIEGENSCHAFT ERMITTELN
    # ---------------------------------------------------------
    einheiten = liegenschaft.einheiten.all()
    total_m2 = sum((e.flaeche_m2 or Decimal('0')) for e in einheiten) or Decimal('1')
    total_m3 = sum((e.volumen_m3 or Decimal('0')) for e in einheiten)
    if total_m3 <= 0: total_m3 = total_m2 # Fallback: m2 nehmen wenn m3 nicht konfiguriert ist
    total_einheiten = einheiten.count() or 1

    # HKVO: verbrauchsabhängige Heizkosten (Grundkosten nach m³ + Verbrauchskosten nach Zähler)
    hkvo_aktiv = getattr(liegenschaft, 'hkvo_aktiv', False)
    grundkosten_anteil = Decimal(getattr(liegenschaft, 'hkvo_grundkosten_prozent', 40)) / Decimal('100')
    verbrauch_map = _heiz_verbrauch_pro_einheit(liegenschaft, start_p, ende_p) if hkvo_aktiv else {}
    total_verbrauch = sum(verbrauch_map.values()) if verbrauch_map else Decimal('0')
    hkvo_angewendet = bool(hkvo_aktiv and total_verbrauch > 0)

    # ---------------------------------------------------------
    # 3. VERTEILUNG AUF EINHEITEN & MIETER (Die Matrix)
    # ---------------------------------------------------------
    abrechnungen = []
    kontroll_summe = Decimal('0.00')

    for einheit in einheiten:
        # Anteil der Einheit am Haus
        e_m2 = einheit.flaeche_m2 or Decimal('0')
        e_m3 = einheit.volumen_m3 or e_m2

        if hkvo_angewendet:
            # Grundkosten nach m³, Verbrauchskosten nach gemessenem Verbrauch (HKVO)
            e_verbrauch = verbrauch_map.get(einheit.id, Decimal('0'))
            grund = pool_heizkosten * grundkosten_anteil * (e_m3 / total_m3)
            verbrauch = pool_heizkosten * (Decimal('1') - grundkosten_anteil) * (e_verbrauch / total_verbrauch)
            anteil_hk_einheit = grund + verbrauch
        else:
            anteil_hk_einheit = pool_heizkosten * (e_m3 / total_m3)
        anteil_nk_einheit = (pool_nk_m2 * (e_m2 / total_m2)) + (pool_nk_einheit * (Decimal('1') / Decimal(total_einheiten)))

        # Mieter in dieser Periode finden
        # Alle Verträge, die die Objekt-Einheit während der Periode BEWOHNT haben —
        # aktiv, gekündigt ODER archiviert (die Zeitüberschneidung unten filtert die
        # Gültigkeit). Nur Entwürfe (nie ein echtes Mietverhältnis) fallen raus.
        # (Früher `aktiv=True` — das schloss mitten in der Periode ausgezogene
        # gekündigte Mieter fälschlich aus, ihr Anteil fiel dann auf Leerstand.)
        vertraege = einheit.vertraege.exclude(status='entwurf').filter(beginn__lte=ende_p).filter(Q(ende__isnull=True) | Q(ende__gte=start_p))

        tage_vermietet_total = 0
        hgt_vermietet_total = Decimal('0.00')

        for vertrag in vertraege.distinct():
            v_start = max(vertrag.beginn, start_p)
            v_ende = min(vertrag.ende, ende_p) if vertrag.ende else ende_p

            tage_bewohnt = (v_ende - v_start).days + 1
            if tage_bewohnt <= 0: continue

            # Gewichtungen ermitteln
            tage_vermietet_total += tage_bewohnt
            zeit_faktor_nk = Decimal(tage_bewohnt) / tage_periode

            overlap_hgt = get_heizgradtage_fuer_zeitraum(v_start, v_ende)
            hgt_vermietet_total += overlap_hgt
            zeit_faktor_hk = overlap_hgt / periode_hgt

            # Kosten für diesen Mieter
            mieter_hk = anteil_hk_einheit * zeit_faktor_hk
            mieter_nk = anteil_nk_einheit * zeit_faktor_nk
            mieter_total_kosten = mieter_hk + mieter_nk

            # Akonto vs. Pauschal Logik (Aus dem Vertrag)
            nk_typ = getattr(vertrag, 'nk_abrechnungsart', 'akonto')

            if nk_typ == 'akonto':
                import calendar as _cal
                nk_monat = vertrag.nebenkosten or Decimal('0.00')
                # Tage des Kalenderjahres (Schaltjahr = 366) statt fix 365 — sonst wird
                # das bezahlte Akonto in Schaltjahren um ~0.27 % zu hoch angesetzt.
                _tage_jahr = Decimal(366 if _cal.isleap(start_p.year) else 365)
                bezahltes_akonto = (nk_monat * 12 / _tage_jahr) * Decimal(tage_bewohnt)
                saldo = mieter_total_kosten - bezahltes_akonto # Positiv = Nachzahlung

                abrechnungen.append({
                    'typ': 'mieter_akonto',
                    'vertrag_id': vertrag.id,
                    'name': f"{vertrag.mieter.vorname} {vertrag.mieter.nachname}",
                    'einheit': einheit.bezeichnung,
                    'von': v_start.strftime('%d.%m.%y'),
                    'bis': v_ende.strftime('%d.%m.%y'),
                    'kosten_anteil': round(mieter_total_kosten, 2),
                    'akonto': round(bezahltes_akonto, 2),
                    'saldo': round(saldo, 2),
                    'nachzahlung': saldo > 0,
                    'info': 'Akonto-Abrechnung'
                })
                kontroll_summe += mieter_total_kosten

            elif nk_typ in ['pauschal', 'inbegriffen']:
                # Pauschal: Kosten fallen an, aber Differenz geht zulasten Eigentümer
                abrechnungen.append({
                    'typ': 'mieter_pauschal',
                    'vertrag_id': vertrag.id,
                    'name': f"{vertrag.mieter.vorname} {vertrag.mieter.nachname}",
                    'einheit': einheit.bezeichnung,
                    'von': v_start.strftime('%d.%m.%y'),
                    'bis': v_ende.strftime('%d.%m.%y'),
                    'kosten_anteil': round(mieter_total_kosten, 2),
                    'akonto': round(mieter_total_kosten, 2), # Pauschale deckt Kosten
                    'saldo': Decimal('0.00'),
                    'nachzahlung': False,
                    'info': f'Als {nk_typ.capitalize()} verrechnet'
                })
                kontroll_summe += mieter_total_kosten

        # Leerstand für Eigentümer ausweisen
        tage_leer = int(tage_periode) - tage_vermietet_total
        hgt_leer = periode_hgt - hgt_vermietet_total

        if tage_leer > 0 or hgt_leer > 0:
            leer_hk = anteil_hk_einheit * (hgt_leer / periode_hgt) if hgt_leer > 0 else Decimal('0')
            leer_nk = anteil_nk_einheit * (Decimal(tage_leer) / tage_periode) if tage_leer > 0 else Decimal('0')
            leer_total = leer_hk + leer_nk

            if leer_total > Decimal('0.01'):
                abrechnungen.append({
                    'typ': 'leerstand',
                    'name': 'Leerstand (Eigentümer)',
                    'einheit': einheit.bezeichnung,
                    'von': '-',
                    'bis': '-',
                    'kosten_anteil': round(leer_total, 2),
                    'akonto': Decimal('0.00'),
                    'saldo': round(leer_total, 2),
                    'nachzahlung': True,
                    'info': 'Leerstandskosten'
                })
                kontroll_summe += leer_total

    abrechnungen.sort(key=lambda x: x['einheit'])

    return {
        'total_kosten': round(total_kosten_gesamt, 2),
        'total_flaeche': round(total_m2, 2),
        'belege_details': kategorien_liste,
        'abrechnungen': abrechnungen,
        'kontroll_summe': round(kontroll_summe, 2),
        'differenz': round(total_kosten_gesamt - kontroll_summe, 2),
        'hkvo_angewendet': hkvo_angewendet,
    }
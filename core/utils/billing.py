# core/utils/billing.py
import datetime
import calendar
from decimal import ROUND_HALF_UP, Decimal
from django.db.models import Sum, Q

from portfolio.models import Liegenschaft, Einheit
from rentals.models import Mietvertrag
from finance.models import AbrechnungsPeriode
from core.services.dokumentsprache import nur_deutsch

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


def _verteile_rundungsrest(zeilen, ziel_total):
    """Legt die Rundungsdifferenz auf einzelne Zeilen, damit die angezeigten
    Kostenanteile sich exakt auf die Gesamtkosten summieren.

    Jeder Anteil wird für sich auf 2 Stellen gerundet. Bei 100.00 auf drei
    gleiche Einheiten ergibt das 3 × 33.33 = 99.99 — der Mieter bekommt eine
    Abrechnung, deren Positionen nicht aufgehen. Bei vielen Einheiten und
    mehreren Kostenarten summieren sich diese Rappen.

    Verfahren: grösster Rest. Die Zeilen mit dem grössten weggerundeten Anteil
    bekommen je einen Rappen dazu (bzw. weg) — das ist die übliche und für den
    Mieter fairste Zuteilung, weil sie dort korrigiert, wo am meisten gerundet
    wurde.

    Begleitfelder wandern mit, sonst wäre die Zeile in sich widersprüchlich:
      akonto/leerstand  saldo bewegt sich mit den Kosten
      pauschal          akonto spiegelt die Kosten, saldo bleibt 0.00
    """
    if not zeilen:
        return
    rappen = Decimal('0.01')
    ist = sum((z['kosten_anteil'] for z in zeilen), Decimal('0.00'))
    diff = (ziel_total - ist).quantize(rappen)
    if diff == 0:
        return
    schritte = int(abs(diff) / rappen)
    richtung = rappen if diff > 0 else -rappen
    # Grösster weggerundeter Rest zuerst; bei Aufrundung umgekehrt, damit der
    # Rappen dort landet, wo er am ehesten hingehört.
    def rest(z):
        exakt = z.get('_exakt')
        if exakt is None:
            return Decimal('0')
        return (Decimal(str(exakt)) - z['kosten_anteil'])
    sortiert = sorted(zeilen, key=rest, reverse=(diff > 0))
    for i in range(min(schritte, len(sortiert))):
        z = sortiert[i]
        z['kosten_anteil'] = (z['kosten_anteil'] + richtung).quantize(rappen)
        if z.get('typ') == 'mieter_pauschal':
            z['akonto'] = (z['akonto'] + richtung).quantize(rappen)
        else:
            z['saldo'] = (z['saldo'] + richtung).quantize(rappen)
            z['nachzahlung'] = z['saldo'] > 0
    for z in zeilen:
        z.pop('_exakt', None)

def _jsonable(obj):
    """Rekursiv JSON-serialisierbar machen: Decimal→str (verlustfrei), date→ISO."""
    from datetime import date as _d, datetime as _dt
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (_d, _dt)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def snapshot_speichern(periode):
    """Friert die aktuelle Abrechnung als JSON auf der Periode ein (beim Verbuchen)."""
    import json
    result = berechne_abrechnung(periode.id)
    periode.snapshot_json = json.dumps(_jsonable(result))
    periode.save(update_fields=['snapshot_json'])
    return result


def hole_abrechnung(periode):
    """Kanonische Abrechnungs-Ausgabe für Anzeige/PDF/Versand.

    Ist die Periode abgeschlossen UND ein Snapshot vorhanden, wird der EINGEFRORENE
    Stand geliefert — so zeigen Detailseite, PDF und Versand exakt die verbuchten
    Zahlen, unabhängig von späteren Änderungen an Belegen/Flächen/Verträgen
    (Live-Test G). Sonst rechnet die Engine live.
    """
    import json
    if getattr(periode, 'abgeschlossen', False) and (periode.snapshot_json or '').strip():
        try:
            return json.loads(periode.snapshot_json)
        except Exception:
            pass
    return berechne_abrechnung(periode.id)


# Fest deutsch: Das Ergebnis landet eingefroren im Snapshot der Periode und
# im deutsch formulierten Abrechnungs-PDF. Mit der Sprache der Sachbearbeitung
# stünden dort übersetzte Kategorien (`get_kategorie_display`).
@nur_deutsch
def akonto_gestellt(vertrag, v_start, v_ende):
    """Akonto-Nebenkosten, die dem Mieter im Zeitraum TATSÄCHLICH gestellt wurden.

    Stresstest 30.09.2026: Die Engine rechnete mit dem heutigen Vertragswert mal
    zwölf Monate und ignorierte, was gestellt worden war. Unterjährige
    Akonto-Anpassungen, Gratismonate und NK-Erlasse flossen nicht ein; der Saldo
    stimmte dann nicht mit dem Mieterkonto überein.

    Je Kalendermonat des Zeitraums:
      · Gibt es die Sollstellungs-Forderung «Miete & NK MM/JJJJ» (nicht storniert),
        zählt ihr NK-Anteil: Haben 3020 abzüglich NK-Erlass (Soll 3091) —
        anteilig, wenn die Periode den Monat nur teilweise deckt.
      · Gibt es sie nicht (Sollstellung nicht gelaufen, Altbestand), gilt der
        Vertragswert für diese Tage — ebenfalls je Monat anteilig.

    Auch ohne jede Sollstellung wird monatsweise gerechnet, nicht mit der
    Jahresformel `nk × 12 / 365 × Tage`: Akonto ist eine Monatsgrösse. Die
    Jahresformel stimmt nur für volle Jahre; bei einem Mieterwechsel im Mai
    schrieb sie dem Vormieter 6.92 zu wenig, dem Nachmieter 8.30 zu viel gut.
    Volle Monate und volle Jahre ergeben unverändert genau den Vertragswert.

    Massgebend ist das GESTELLTE, nicht das bezahlte Akonto: Unbezahltes bleibt
    als offene Forderung im Mieterkonto und würde sonst zweimal verlangt.
    Gibt (betrag, anzahl_monate_aus_buchungen) zurück.
    """
    from finance.models import Buchung, DebitorenRechnung

    nk_monat = vertrag.nebenkosten or Decimal('0.00')
    gesamt = Decimal('0.00')
    aus_buchungen = 0
    j, m = v_start.year, v_start.month
    while (j, m) <= (v_ende.year, v_ende.month):
        letzter = calendar.monthrange(j, m)[1]
        m_start, m_ende = datetime.date(j, m, 1), datetime.date(j, m, letzter)
        von, bis = max(v_start, m_start), min(v_ende, m_ende)
        tage = (bis - von).days + 1
        if tage > 0:
            rechnung = (DebitorenRechnung.alle_organisationen
                        .filter(vertrag=vertrag, titel=f"Miete & NK {m:02d}/{j}")
                        .exclude(status='storniert').first())
            gestellt = None
            if rechnung is not None:
                basis = Buchung.alle_organisationen.filter(
                    debitoren_rechnung=rechnung, ist_storno=False, storniert_am__isnull=True)
                haben = basis.filter(haben_konto__nummer='3020').aggregate(s=Sum('betrag'))['s']
                if haben is not None:
                    erlass = basis.filter(soll_konto__nummer='3091').aggregate(s=Sum('betrag'))['s'] or Decimal('0')
                    gestellt = Decimal(haben) - Decimal(erlass)
            if gestellt is not None:
                # Vertragstage des Monats (Einzug/Auszug mitten im Monat): darauf bezog
                # sich die Forderung. Die Periode deckt davon `tage`.
                v_von = max(vertrag.beginn, m_start)
                v_bis = min(vertrag.ende, m_ende) if vertrag.ende else m_ende
                v_tage = max((v_bis - v_von).days + 1, 1)
                gesamt += gestellt * Decimal(min(tage, v_tage)) / Decimal(v_tage)
                aus_buchungen += 1
            else:
                # Lücke im gemischten Fall: der Monatswert für diese Tage (volle
                # Monate ergeben genau den Vertragswert, ohne Tagesrundungsreste).
                gesamt += nk_monat * Decimal(tage) / Decimal(letzter)
        m += 1
        if m == 13:
            j, m = j + 1, 1
    return gesamt, aus_buchungen


#: Kategorie des Belegs → Kostenart der Verteilschlüssel (`Verteilschluessel.KOSTENART_CHOICES`).
_BELEG_KOSTENART = {
    'wasser': 'wasser', 'hauswart': 'hauswartung', 'strom': 'allgemeinstrom', 'lift': 'lift',
    'verwaltung': 'verwaltung', 'tv': 'kabel_tv', 'kehricht': 'sonstiges', 'diverse': 'sonstiges',
}
#: Standardkonto (`finance.booking.STANDARD_KONTEN`) → Kostenart. Damit tragen auch die
#: Kreditoren eine Kostenart und folgen dem Schlüssel, der für sie gewählt ist. Eigene Konten
#: einer Verwaltung fallen unter «Sonstige» — es sei denn, ihr Name nennt die Heizung.
_KONTO_KOSTENART = {
    '4100': 'heizung', '4110': 'wasser', '4120': 'hauswartung', '4130': 'allgemeinstrom',
    '4140': 'sonstiges', '4400': 'versicherung', '4500': 'verwaltung',
}
#: Schlüsselarten, die über die Tabelle der Liegenschaft angewendet werden (opt-in über
#: `Liegenschaft.verteilschluessel_aktiv`). «Pauschal» (CHF je Einheit) ist fachlich offen und
#: wird nicht geraten. Heizkosten bleiben bei HKVO/Heizgradtagen.
_STD_TYPEN = ('zimmer', 'anteil', 'prozent', 'm2', 'm3', 'einheit', 'personen')
#: Arten, deren Anteil je Einheit feststeht und zeitanteilig nach Tagen geht.
_ARTEN_TAGE = ('m2', 'm3', 'einheit', 'zimmer', 'anteil', 'prozent')

#: Was die Periode für den Leerstand bei Kosten nach Personen vorsieht (Entscheid E3).
LEERSTAND_PERSONEN_KEINE = 'keine'
LEERSTAND_PERSONEN_DURCHSCHNITT = 'durchschnitt'

RAPPEN = Decimal('0.01')


def kostenart_beleg(beleg):
    """Kostenart eines manuellen Belegs."""
    if beleg.kategorie == 'heizung':
        return 'heizung'
    return _BELEG_KOSTENART.get(beleg.kategorie, 'sonstiges')


def kostenart_konto(konto):
    """Kostenart eines Buchungskontos (Kreditor oder Position)."""
    if konto is None:
        return 'sonstiges'
    bez = (konto.bezeichnung or '').lower()
    if 'heiz' in bez or 'wärme' in bez:
        return 'heizung'
    return _KONTO_KOSTENART.get(konto.nummer, 'sonstiges')


def hnk_kreditoren(liegenschaft, start_p, ende_p):
    """Die Kreditorenrechnungen, die in die Abrechnung einfliessen — EINE Abfrage für Engine,
    Wizard und Leseansicht (Fehler c: die Detailansicht filterte bis hierher nach `datum`).

    Mit Leistungsperiode zählt die Überschneidung, ohne sie das Rechnungsdatum.
    """
    from finance.models import KreditorenRechnung
    return (KreditorenRechnung.objects.filter(
        liegenschaft=liegenschaft, is_hnk_relevant=True, status__in=['freigegeben', 'bezahlt'],
    ).filter(
        Q(leistungs_von__lte=ende_p) & Q(leistungs_bis__gte=start_p) |
        Q(leistungs_von__isnull=True, datum__range=[start_p, ende_p])
    ).select_related('konto').prefetch_related('positionen__konto').order_by('datum', 'id'))


def leistungs_anteil(kred, start_p, ende_p):
    """Anteil einer Rechnung an der Periode: (Faktor, Tage in der Periode, Tage der Leistung).

    Fehler c: Eine Rechnung zählte voll, sobald ihre Leistungsperiode die Abrechnung nur
    berührte — eine Jahresrechnung Juli–Juni floss so ganz in das Kalenderjahr. Jetzt anteilig
    nach Tagen. Ohne vollständige Leistungsperiode bleibt es beim ganzen Betrag (Faktor 1).
    """
    von, bis = kred.leistungs_von, kred.leistungs_bis
    if not (von and bis) or bis < von:
        return Decimal('1'), None, None
    tage_l = (bis - von).days + 1
    tage_p = max(0, (min(bis, ende_p) - max(von, start_p)).days + 1)
    return Decimal(tage_p) / Decimal(tage_l), tage_p, tage_l


def _hnk_teile(kred):
    """Split-aware: die tatsächlich HNK-relevanten Kostenteile einer Rechnung.
    Mit Kostenaufteilung nur die HNK-Positionen (Betrag + eigenes Konto), sonst
    die ganze Rechnung. So fliesst z.B. bei einer 300er-Rechnung mit nur 100 HNK
    auch nur 100 in die Nebenkostenabrechnung — nicht mehr der volle Betrag."""
    positionen = list(kred.positionen.all())
    if positionen:
        return [(p.betrag or Decimal('0.00'), p.konto,
                 f"{kred.lieferant} ({p.konto.bezeichnung}{f' · {p.bezeichnung}' if p.bezeichnung else ''})")
                for p in positionen if p.is_hnk_relevant]
    return [(kred.betrag or Decimal('0.00'), kred.konto,
             f"{kred.lieferant} ({kred.konto.bezeichnung if kred.konto else 'Kreditor'})")]


def _standard_schluessel(liegenschaft, stichtag):
    """Je Kostenart der zum Stichtag gültige Standard-Schlüssel (neuester `gueltig_ab`).

    Nur die Typen in `_STD_TYPEN`. Gibt {kostenart: LiegenschaftVerteilschluessel} zurück.
    Gültig heisst: `gueltig_ab` <= Stichtag und (`gueltig_bis` leer oder >= Stichtag). Der
    Stichtag ist das Periodenende; ein Schlüsselwechsel innerhalb der Periode wird nicht
    anteilig gerechnet.
    """
    result = {}
    for s in liegenschaft.standard_schluessel.filter(gueltig_ab__lte=stichtag).order_by('gueltig_ab', 'id'):
        if s.gueltig_bis and s.gueltig_bis < stichtag:
            continue
        if s.kostenart == 'heizung' or s.typ not in _STD_TYPEN:
            continue
        result[s.kostenart] = s            # der spätere gueltig_ab überschreibt den früheren
    return result


def _std_anteile(typ, kostenart, einheiten, stichtag):
    """Verteilbasis eines Standard-Schlüssels: ({einheit_id: Anteil, Summe 1}, None) oder (None, Grund).

    Ohne verwertbare Basis gibt es keinen Anteil, sondern einen Grund — der Aufrufer verteilt
    dann nach Fläche und meldet es, damit die Kosten nicht verschwinden.
    """
    if typ == 'zimmer':
        werte = {e.id: (e.zimmer or Decimal('0')) for e in einheiten}
        quelle = 'Zimmerzahl'
    elif typ == 'anteil':
        werte = {e.id: (e.wertquote or Decimal('0')) for e in einheiten}
        quelle = 'Wertquote'
    else:  # prozent: je Einheit erfasst
        werte = {}
        for e in einheiten:
            zeilen = [z for z in e.verteilschluessel.filter(kostenart=kostenart, typ='prozent',
                                                            gueltig_ab__lte=stichtag).order_by('gueltig_ab', 'id')
                      if not z.gueltig_bis or z.gueltig_bis >= stichtag]
            werte[e.id] = zeilen[-1].wert if zeilen else Decimal('0')
        total = sum(werte.values(), Decimal('0'))
        if abs(total - Decimal('100')) > Decimal('0.01'):
            return None, f"Die Prozentanteile ({kostenart}) ergeben {total} statt 100"
        return {i: w / Decimal('100') for i, w in werte.items()}, None
    total = sum(werte.values(), Decimal('0'))
    if total <= 0:
        return None, f"Bei keiner Einheit ist {quelle} erfasst"
    return {i: w / total for i, w in werte.items()}, None


def _volumen_basis(einheiten):
    """Basis für «nach Volumen»: ({einheit_id: Wert}, 'm3' | 'm2', [Einheiten ohne m³]).

    Fehler b: Die Summe zählte nur erfasste m³, der Anteil einer Einheit ohne m³ fiel aber auf
    ihre m² zurück — zusammen mehr als 100 %. Jetzt einheitlich: Haben alle Einheiten mit
    Fläche auch ein Volumen, gilt m³. Fehlt es bei einem Teil, gilt für ALLE die Fläche, und der
    Aufrufer warnt. Einheiten ganz ohne Mass (Keller, Parkplatz ohne Angaben) tragen 0.
    """
    ohne = [e for e in einheiten if not (e.volumen_m3 or 0) > 0 and (e.flaeche_m2 or 0) > 0]
    mit = [e for e in einheiten if (e.volumen_m3 or 0) > 0]
    if mit and not ohne:
        return {e.id: (e.volumen_m3 or Decimal('0')) for e in einheiten}, 'm3', []
    return {e.id: (e.flaeche_m2 or Decimal('0')) for e in einheiten}, 'm2', (ohne if mit else [])


def _ist_heizzaehler(z):
    typ = (z.typ or '').lower()
    return any(t in typ for t in ('heiz', 'wärme', 'waerme', 'wmz', 'energie', 'wärmemenge'))


def _heiz_staende(liegenschaft, start_p, ende_p):
    """{einheit_id: [[ZaehlerStand, …] je Heizzähler mit Verbrauch > 0]} — Stände in der Periode."""
    from portfolio.models import Zaehler, ZaehlerStand
    result = {}
    for z in Zaehler.objects.filter(einheit__liegenschaft=liegenschaft):
        if not _ist_heizzaehler(z):
            continue
        staende = list(ZaehlerStand.objects.filter(
            zaehler=z, datum__gte=start_p, datum__lte=ende_p).order_by('datum', 'id'))
        if len(staende) >= 2 and (staende[-1].wert or 0) - (staende[0].wert or 0) > 0:
            result.setdefault(z.einheit_id, []).append(staende)
    return result


def _heiz_verbrauch_pro_einheit(liegenschaft, start_p, ende_p):
    """Verbrauch (Zählerdifferenz) pro Einheit für Heizungs-/Wärmezähler im Zeitraum.
    Gibt {einheit_id: verbrauch} zurück; leer, wenn keine verwertbaren Zählerstände existieren."""
    result = {}
    for eid, je_zaehler in _heiz_staende(liegenschaft, start_p, ende_p).items():
        for staende in je_zaehler:
            result[eid] = result.get(eid, Decimal('0')) + (staende[-1].wert - staende[0].wert)
    return result


def _stand_an_grenze(staende, tag):
    """Der Stand an einer Grenze zwischen zwei Mietverhältnissen: am letzten Tag des
    bisherigen oder am ersten Tag des neuen. Ein als «Zwischenstand» erfasster geht vor."""
    kandidaten = [s for s in staende if s.datum in (tag - datetime.timedelta(days=1), tag)]
    if not kandidaten:
        return None
    zwischen = [s for s in kandidaten if getattr(s, 'art', '') == 'zwischen']
    return (zwischen or kandidaten)[-1].wert


def _verbrauch_im_zeitraum(je_zaehler, von, bis, start_p, ende_p):
    """Gemessener Verbrauch einer Einheit von `von` bis `bis`, oder None, wenn an einer
    inneren Grenze der Stand fehlt. Periodenanfang/-ende: erster bzw. letzter Stand."""
    total = Decimal('0')
    for staende in je_zaehler:
        a = staende[0].wert if von <= start_p else _stand_an_grenze(staende, von)
        e = staende[-1].wert if bis >= ende_p else _stand_an_grenze(staende, bis + datetime.timedelta(days=1))
        if a is None or e is None:
            return None
        total += e - a
    return total


def _runde(betrag):
    return Decimal(betrag).quantize(RAPPEN, rounding=ROUND_HALF_UP)


def _aufschluesselung(teile, kosten_anteil):
    """Je Kostenart gerundet, Restrappen auf die grösste Position — die Aufschlüsselung einer
    Zeile summiert sich genau auf ihren Kostenanteil."""
    zeilen = [{'kostenart': ka, 'betrag': round(b, 2)} for ka, b in sorted(teile.items()) if abs(b) >= Decimal('0.005')]
    if zeilen:
        rest = kosten_anteil - sum((z['betrag'] for z in zeilen), Decimal('0.00'))
        if rest:
            max(zeilen, key=lambda z: z['betrag'])['betrag'] += rest
    return zeilen


def berechne_abrechnung(periode_id):
    """
    Professionelle Schweizer HNK-Abrechnung (Expert-Version).
    Beinhaltet: Shift-Left (Kreditoren), Heizgradtage, Bestandesrechnung Öl, Pauschal vs. Akonto.

    Kosten werden je (Kostenart, Verteilart) gesammelt. Die Kostenart trägt die vertraglich
    ausgeschlossenen Kosten (E2) und die Aufschlüsselung je Mieter; die Verteilart bestimmt,
    wie verteilt wird:
      heiz      Volumen (bzw. HKVO: Grund nach Volumen, Rest nach Zähler), zeitlich nach Heizgradtagen
      m2 / m3   Fläche bzw. Volumen, zeitlich nach Tagen
      einheit   je Einheit gleich, nach Tagen
      personen  Personenzahl × bewohnte Tage
      zimmer / anteil / prozent  Tabelle der Liegenschaft, nach Tagen
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
    pools = {}                          # (kostenart, verteilart) → Betrag

    def _dazu(ka, art, betrag):
        pools[(ka, art)] = pools.get((ka, art), Decimal('0.00')) + betrag

    kategorien_liste = []
    warnungen = []
    warnung_arten = []                  # parallel zu `warnungen`: wozu die Warnung gehört
    hinweise = []

    def _warn(art, text):
        warnungen.append(text)
        warnung_arten.append(art)

    # Verteilschlüssel der Liegenschaft (nur wenn freigeschaltet): Kosten, deren Kostenart einen
    # Standard-Schlüssel hat, werden nach diesem verteilt — Belege wie Kreditoren.
    std_schluessel = (_standard_schluessel(liegenschaft, ende_p)
                      if getattr(liegenschaft, 'verteilschluessel_aktiv', False) else {})

    # A) Manuelle Belege (NebenkostenBeleg)
    for beleg in periode.belege.all():
        betrag = beleg.betrag or Decimal('0.00')
        if betrag <= 0: continue
        ka = kostenart_beleg(beleg)

        _std = std_schluessel.get(ka)
        if _std is not None and ka != 'heizung':
            _dazu(ka, _std.typ, betrag)
            schluessel = _std.typ
        elif beleg.kategorie == 'heizung' or beleg.verteilschluessel == 'm3':
            _dazu(ka, 'heiz', betrag)
            schluessel = beleg.verteilschluessel
        elif beleg.verteilschluessel in ('einheit', 'personen'):
            _dazu(ka, beleg.verteilschluessel, betrag)
            schluessel = beleg.verteilschluessel
        else:
            _dazu(ka, 'm2', betrag)
            schluessel = beleg.verteilschluessel

        kategorien_liste.append({
            'datum': beleg.datum, 'text': beleg.text, 'kategorie': beleg.get_kategorie_display(),
            'betrag': betrag, 'schluessel': schluessel, 'quelle': 'Beleg', 'kostenart': ka,
        })

    # B) Kreditoren aus Finanzmodul einlesen (Die Automatisierung)
    zukauf_oel_l = Decimal('0.00')
    zukauf_oel_chf = Decimal('0.00')

    for kred in hnk_kreditoren(liegenschaft, start_p, ende_p):
        teile = _hnk_teile(kred)
        # Bestandes-Zukäufe (Öl/Gas) — Menge am Kopf. Fehler d: zählte den vollen
        # Rechnungsbetrag und übersah die Positionen; jetzt nur die HNK-Teile, wie bei
        # jeder anderen Rechnung. Ein Zukauf geht in den Tank und wird NICHT nach der
        # Leistungsperiode abgegrenzt — verbraucht wird über die Bestandesrechnung (C).
        if kred.menge_liter and kred.menge_liter > 0:
            betrag = sum((b for b, _k, _t in teile), Decimal('0.00'))
            if betrag <= 0: continue
            zukauf_oel_l += kred.menge_liter
            zukauf_oel_chf += betrag
            kategorien_liste.append({
                'datum': kred.datum, 'text': f"{kred.lieferant} (Öl-Einkauf {kred.menge_liter}L)",
                'kategorie': 'Öl-Einkauf (Bestand)', 'betrag': betrag, 'schluessel': 'm3', 'quelle': 'FiBu',
                'kostenart': 'heizung',
            })
            continue # Wird in Schritt C abgerechnet

        faktor, tage_in, tage_l = leistungs_anteil(kred, start_p, ende_p)
        # Direkte Kosten zuweisen — pro HNK-Teil (Split-aware)
        for betrag, konto, text in teile:
            if betrag <= 0: continue
            if faktor != 1:
                betrag = _runde(betrag * faktor)
                text = f"{text} · anteilig {tage_in}/{tage_l} Tage"
                if betrag <= 0: continue
            ka = kostenart_konto(konto)
            _std = std_schluessel.get(ka)
            v_key = konto.standard_verteilschluessel if konto and konto.standard_verteilschluessel else 'm2'
            if _std is not None and ka != 'heizung':
                _dazu(ka, _std.typ, betrag)
                v_key = _std.typ
            elif konto and ('heiz' in konto.bezeichnung.lower() or 'wärme' in konto.bezeichnung.lower()):
                _dazu(ka, 'heiz', betrag)
                v_key = 'm3'
            elif v_key in ('einheit', 'personen'):
                _dazu(ka, v_key, betrag)
            elif v_key == 'm3':
                _dazu(ka, 'heiz', betrag)
            else:
                _dazu(ka, 'm2', betrag)
            kategorien_liste.append({
                'datum': kred.datum, 'text': text,
                'kategorie': 'Kreditor', 'betrag': betrag, 'schluessel': v_key, 'quelle': 'FiBu',
                'kostenart': ka,
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

        if end_l > total_l:
            # Mehr Öl im Tank als Anfangsbestand + Zukäufe: Erfassungsfehler. Ohne
            # Hinweis fiele der Öl-Posten still weg und die Heizkosten wären 0.
            _warn('oel',
                f"Endbestand Heizöl ({end_l} L) ist grösser als Anfangsbestand plus Zukäufe "
                f"({total_l} L) — der Heizöl-Verbrauch konnte nicht berechnet werden. "
                "Bitte Bestände und Öl-Rechnungen prüfen.")

        if effektive_oel_kosten > 0:
            _dazu('heizung', 'heiz', effektive_oel_kosten)
            kategorien_liste.append({
                'datum': ende_p, 'text': "Effektiver Heizöl-Verbrauch (Anfang + Zukauf - Endbestand)",
                'kategorie': 'Heizmaterial', 'betrag': round(effektive_oel_kosten, 2), 'schluessel': 'm3',
                'quelle': 'Bestand', 'kostenart': 'heizung',
            })

    # D) Verwaltungshonorar auf die Nebenkosten — Satz aus den Account-Einstellungen
    # (Verwaltung.nk_honorar_prozent, Standard 3 %); 0 % = kein Honorar-Posten.
    # Der Satz kommt aus der Verwaltung DIESER Periode, nicht aus der
    # ersten der Installation. Das Honorar ist ein Geldbetrag auf einer
    # Abrechnung, die dem Mieter zugestellt wird — mit dem Satz einer
    # fremden Verwaltung gerechnet ist sie schlicht falsch.
    #
    # Der Alias `_Vw` liess `Organisation.objects.first()` durch jede
    # Suche nach genau dieser Zeichenkette fallen (Audit 18.08.2026).
    #
    # Fehler e: Das Honorar auf die Heizkosten lag im Flächen-Topf und wurde damit nach m²
    # verteilt, während die Heizkosten selbst nach HKVO/Volumen gehen. Jetzt folgt es den
    # Heizkosten; das Honorar auf die übrigen Kosten bleibt nach Fläche.
    _vw = getattr(periode, 'organisation', None)
    _satz_pct = _vw.nk_honorar_prozent if _vw else Decimal('3.00')
    honorarsatz = (_satz_pct or Decimal('0')) / Decimal('100')
    heiz_basis_honorar = sum((b for (ka, art), b in pools.items() if art == 'heiz'), Decimal('0.00'))
    rest_basis_honorar = sum((b for (ka, art), b in pools.items() if art != 'heiz'), Decimal('0.00'))
    honorar_heiz = heiz_basis_honorar * honorarsatz
    honorar_rest = rest_basis_honorar * honorarsatz
    if honorar_heiz > 0:
        _dazu('verwaltung', 'heiz', honorar_heiz)
        kategorien_liste.append({
            'datum': ende_p, 'text': f"Verwaltungshonorar auf Heizkosten ({_satz_pct}%)",
            'kategorie': 'Verwaltung', 'betrag': round(honorar_heiz, 2), 'schluessel': 'm3',
            'quelle': 'System', 'kostenart': 'verwaltung',
        })
    if honorar_rest > 0:
        _dazu('verwaltung', 'm2', honorar_rest)
        kategorien_liste.append({
            'datum': ende_p, 'text': f"Verwaltungshonorar ({_satz_pct}%)",
            'kategorie': 'Verwaltung', 'betrag': round(honorar_rest, 2), 'schluessel': 'm2',
            'quelle': 'System', 'kostenart': 'verwaltung',
        })

    # ---------------------------------------------------------
    # 2. GESAMT-BASIS DER LIEGENSCHAFT ERMITTELN
    # ---------------------------------------------------------
    einheiten = list(liegenschaft.einheiten.all())
    _real_total_m2 = sum((e.flaeche_m2 or Decimal('0')) for e in einheiten)
    total_m2 = _real_total_m2 or Decimal('1')
    m3_werte, m3_basis, m3_fehlend = _volumen_basis(einheiten)
    total_m3 = sum(m3_werte.values(), Decimal('0')) or total_m2
    total_einheiten = len(einheiten) or 1
    if m3_fehlend and any(art in ('heiz', 'm3') for (_ka, art) in pools):
        _warn('volumen',
            "Volumen (m³) fehlt bei: " + ", ".join(e.bezeichnung for e in m3_fehlend) +
            " — die Kosten nach Volumen wurden für alle Einheiten nach Fläche (m²) verteilt, "
            "damit die Anteile 100 % ergeben. Bitte das Volumen ergänzen.")

    vertraege_je_einheit = {}
    for e in einheiten:
        vertraege_je_einheit[e.id] = list(
            e.vertraege.exclude(status='entwurf').filter(beginn__lte=ende_p)
            .filter(Q(ende__isnull=True) | Q(ende__gte=start_p)).distinct()
            .select_related('mieter').order_by('beginn', 'id'))

    def _zeitraum(v):
        vs = max(v.beginn, start_p)
        ve = min(v.ende, ende_p) if v.ende else ende_p
        return vs, ve, (ve - vs).days + 1

    # Personen-Basis (Live-Test G): Summe (Personenzahl × bewohnte Tage) über alle
    # in der Periode gültigen Verträge. Personenabhängige Kosten (z.B. Kehricht,
    # Wasser) werden danach verteilt. Ist niemand da (total_person_tage 0), fällt der
    # Pool auf die Flächenverteilung zurück, damit die Kosten nicht verschwinden.
    #
    # Leerstand (Entscheid E3): Standard «keine» — der Leerstand hat 0 Personen und trägt
    # nichts, der Pool geht voll auf die Bewohner. «durchschnitt» — jede Leerstandszeile
    # trägt nach der durchschnittlichen Belegung der belegten Einheiten.
    personen_pool = sum((b for (ka, art), b in pools.items() if art == 'personen'), Decimal('0.00'))
    total_person_tage = Decimal('0')
    belegt_tage = Decimal('0')
    leer_person_tage = {}
    modus_leer = getattr(periode, 'leerstand_personen', LEERSTAND_PERSONEN_KEINE) or LEERSTAND_PERSONEN_KEINE
    personen_leer_tage = 0
    if personen_pool > 0:
        for e in einheiten:
            tage_e = 0
            for v in vertraege_je_einheit[e.id]:
                _vs, _ve, t = _zeitraum(v)
                if t > 0:
                    total_person_tage += Decimal(max(1, v.anzahl_personen or 1)) * t
                    belegt_tage += t
                    tage_e += t
            leer = int(tage_periode) - tage_e
            if leer > 0:
                personen_leer_tage += leer
                leer_person_tage[e.id] = Decimal(leer)
        if modus_leer == LEERSTAND_PERSONEN_DURCHSCHNITT and belegt_tage > 0:
            durchschnitt = total_person_tage / belegt_tage
            leer_person_tage = {eid: t * durchschnitt for eid, t in leer_person_tage.items()}
            total_person_tage += sum(leer_person_tage.values(), Decimal('0'))
        else:
            leer_person_tage = {}
        if total_person_tage <= 0:
            for (ka, art) in [k for k in pools if k[1] == 'personen']:
                _dazu(ka, 'm2', pools.pop((ka, art)))
            personen_pool = Decimal('0.00')

    # Standard-Schlüssel der Liegenschaft: Anteile je (Kostenart, Typ). Fehlt die Basis, wird
    # nach Fläche verteilt und gewarnt (Kosten dürfen nicht verschwinden).
    std_anteile = {}
    for (ka, art) in [k for k in pools if k[1] in ('zimmer', 'anteil', 'prozent')]:
        anteile, grund = _std_anteile(art, ka, einheiten, ende_p)
        if anteile is None:
            betrag = pools.pop((ka, art))
            _dazu(ka, 'm2', betrag)
            _warn('schluessel', f"Verteilschlüssel «{art}» für {ka} nicht anwendbar: {grund}. "
                             f"Die Kosten (CHF {betrag}) wurden nach Fläche verteilt.")
            continue
        std_anteile[(ka, art)] = anteile

    total_kosten_gesamt = sum(pools.values(), Decimal('0.00'))
    pool_heiz = sum((b for (ka, art), b in pools.items() if art == 'heiz'), Decimal('0.00'))

    # HKVO: verbrauchsabhängige Heizkosten (Grundkosten nach m³ + Verbrauchskosten nach Zähler)
    hkvo_aktiv = getattr(liegenschaft, 'hkvo_aktiv', False)
    grundkosten_anteil = Decimal(getattr(liegenschaft, 'hkvo_grundkosten_prozent', 40)) / Decimal('100')
    heiz_staende = _heiz_staende(liegenschaft, start_p, ende_p) if hkvo_aktiv else {}
    verbrauch_map = {eid: sum((s[-1].wert - s[0].wert for s in je), Decimal('0'))
                     for eid, je in heiz_staende.items()}
    total_verbrauch = sum(verbrauch_map.values()) if verbrauch_map else Decimal('0')
    hkvo_angewendet = bool(hkvo_aktiv and total_verbrauch > 0)
    if hkvo_aktiv and not hkvo_angewendet:
        _warn('hkvo', "HKVO ist aktiv, aber es liegen keine verwertbaren Zählerstände vor "
                         "(je Zähler mindestens zwei Stände in der Periode). Die Heizkosten wurden "
                         "ausschliesslich nach Volumen verteilt.")
    elif hkvo_angewendet:
        _ohne_zaehler = [e.bezeichnung for e in einheiten if verbrauch_map.get(e.id, Decimal('0')) <= 0]
        if _ohne_zaehler:
            _warn('hkvo', "HKVO: Kein Verbrauch erfasst bei " + ", ".join(_ohne_zaehler) +
                             " — der Verbrauchsanteil dieser Einheiten ist 0, die Verbrauchskosten "
                             "fallen auf die übrigen. Bitte Zählerstände ergänzen.")

    # ---------------------------------------------------------
    # 3. VERTEILUNG AUF EINHEITEN & MIETER (Die Matrix)
    # ---------------------------------------------------------
    abrechnungen = []

    def _zeile_dazu(zeile, teile, exakt):
        zeile['_exakt'] = exakt
        zeile['_teile'] = teile
        abrechnungen.append(zeile)

    for einheit in einheiten:
        # Anteil der Einheit am Haus, je Pool (ohne Personen: die gehen je Vertrag)
        e_m2 = einheit.flaeche_m2 or Decimal('0')
        e_m3 = m3_werte.get(einheit.id, Decimal('0'))
        f_art = {
            'm2': e_m2 / total_m2,
            'm3': e_m3 / total_m3,
            'einheit': Decimal('1') / Decimal(total_einheiten),
        }
        anteil_tage = {}                 # (ka, art) → Anteil der Einheit, zeitanteilig nach Tagen
        heiz_grund, heiz_verbrauch = {}, {}   # ka → Anteil der Einheit, zeitanteilig nach HGT bzw. Zähler
        e_verbrauch = verbrauch_map.get(einheit.id, Decimal('0'))
        for (ka, art), betrag in pools.items():
            if art == 'heiz':
                if hkvo_angewendet:
                    # Grundkosten nach m³, Verbrauchskosten nach gemessenem Verbrauch (HKVO)
                    heiz_grund[ka] = betrag * grundkosten_anteil * (e_m3 / total_m3)
                    heiz_verbrauch[ka] = betrag * (Decimal('1') - grundkosten_anteil) * (e_verbrauch / total_verbrauch)
                else:
                    heiz_grund[ka] = betrag * (e_m3 / total_m3)
            elif art in ('m2', 'm3', 'einheit'):
                anteil_tage[(ka, art)] = betrag * f_art[art]
            elif (ka, art) in std_anteile:
                anteil_tage[(ka, art)] = betrag * std_anteile[(ka, art)].get(einheit.id, Decimal('0'))

        # Mieter in dieser Periode finden
        # Alle Verträge, die die Objekt-Einheit während der Periode BEWOHNT haben —
        # aktiv, gekündigt ODER archiviert (die Zeitüberschneidung filtert die
        # Gültigkeit). Nur Entwürfe (nie ein echtes Mietverhältnis) fallen raus.
        # (Früher `aktiv=True` — das schloss mitten in der Periode ausgezogene
        # gekündigte Mieter fälschlich aus, ihr Anteil fiel dann auf Leerstand.)
        vertraege = vertraege_je_einheit[einheit.id]

        # Zwischenstand beim Mieterwechsel: Ist er für jede Grenze erfasst (und überlappen
        # sich die Verträge nicht), wird der Verbrauch nach Zähler geteilt. Sonst wie
        # bisher nach Heizgradtagen — und die Zeile sagt es.
        verbrauch_je_vertrag = None
        teilweise = any(_zeitraum(v)[0] > start_p or _zeitraum(v)[1] < ende_p for v in vertraege)
        if hkvo_angewendet and e_verbrauch > 0 and vertraege:
            zeitraeume = [_zeitraum(v) for v in vertraege]
            ueberlappt = any(zeitraeume[i][1] >= zeitraeume[i + 1][0] for i in range(len(zeitraeume) - 1))
            if not ueberlappt:
                gemessen = {v.id: _verbrauch_im_zeitraum(heiz_staende[einheit.id], vs, ve, start_p, ende_p)
                            for v, (vs, ve, _t) in zip(vertraege, zeitraeume)}
                if all(m is not None for m in gemessen.values()):
                    verbrauch_je_vertrag = gemessen
            if verbrauch_je_vertrag is None and teilweise:
                hinweise.append(f"{einheit.bezeichnung}: Mieterwechsel oder Leerstand ohne Zwischenstand — "
                                "der Heizverbrauch wurde nach Heizgradtagen aufgeteilt.")

        tage_vermietet_total = 0
        hgt_vermietet_total = Decimal('0.00')
        verbrauch_vermietet = Decimal('0')

        for vertrag in vertraege:
            v_start, v_ende, tage_bewohnt = _zeitraum(vertrag)
            if tage_bewohnt <= 0: continue

            # Gewichtungen ermitteln
            tage_vermietet_total += tage_bewohnt
            zeit_faktor_nk = Decimal(tage_bewohnt) / tage_periode

            overlap_hgt = get_heizgradtage_fuer_zeitraum(v_start, v_ende)
            hgt_vermietet_total += overlap_hgt
            zeit_faktor_hk = overlap_hgt / periode_hgt
            if verbrauch_je_vertrag is not None:
                faktor_verbrauch = verbrauch_je_vertrag[vertrag.id] / e_verbrauch
                verbrauch_vermietet += verbrauch_je_vertrag[vertrag.id]
            else:
                faktor_verbrauch = zeit_faktor_hk

            # Kosten für diesen Mieter, je Kostenart
            teile = {}
            for ka, b in heiz_grund.items():
                teile[ka] = teile.get(ka, Decimal('0')) + b * zeit_faktor_hk
            for ka, b in heiz_verbrauch.items():
                teile[ka] = teile.get(ka, Decimal('0')) + b * faktor_verbrauch
            for (ka, art), b in anteil_tage.items():
                teile[ka] = teile.get(ka, Decimal('0')) + b * zeit_faktor_nk
            # Personenabhängiger Anteil: (Personenzahl × bewohnte Tage) am Total
            # aller Personen-Tage der Liegenschaft (Live-Test G).
            if total_person_tage > 0 and personen_pool > 0:
                pt = Decimal(max(1, vertrag.anzahl_personen or 1)) * Decimal(tage_bewohnt)
                for (ka, art), b in pools.items():
                    if art == 'personen':
                        teile[ka] = teile.get(ka, Decimal('0')) + b * pt / total_person_tage

            # Akonto vs. Pauschal Logik (Aus dem Vertrag)
            nk_typ = getattr(vertrag, 'nk_abrechnungsart', 'akonto')
            # E2 (Art. 257a Abs. 2 OR): Was der Vertrag ausschliesst, trägt dieser Mieter nicht.
            # Fehler a: «direkt» zählte die Tage, erzeugte aber keine Zeile — die Kosten
            # verschwanden. Beides geht jetzt auf eine Eigentümerzeile.
            if nk_typ == 'direkt':
                ausgeschlossen = set(teile)
            else:
                ausgeschlossen = set(getattr(vertrag, 'ausgeschlossene_kostenarten', None) or []) & set(teile)
            teile_eig = {ka: b for ka, b in teile.items() if ka in ausgeschlossen}
            teile = {ka: b for ka, b in teile.items() if ka not in ausgeschlossen}
            mieter_total_kosten = sum(teile.values(), Decimal('0'))
            name = f"{vertrag.mieter.vorname} {vertrag.mieter.nachname}"
            basis = {
                'einheit': einheit.bezeichnung, 'einheit_id': einheit.id, 'flaeche': einheit.flaeche_m2,
                'von': v_start.strftime('%d.%m.%y'),
                'bis': v_ende.strftime('%d.%m.%y'),
                'tage': tage_bewohnt,
            }
            heiz_basis = None
            if hkvo_angewendet and e_verbrauch > 0 and teilweise:
                heiz_basis = 'zaehler' if verbrauch_je_vertrag is not None else 'heizgradtage'

            if nk_typ == 'akonto':
                # Das TATSÄCHLICH gestellte Akonto (Sollstellung), je Monat — nur wo keine
                # Forderung existiert, gilt der Vertragswert (siehe `akonto_gestellt`).
                bezahltes_akonto, _n_buch = akonto_gestellt(vertrag, v_start, v_ende)
                saldo = mieter_total_kosten - bezahltes_akonto # Positiv = Nachzahlung
                _zeile_dazu({
                    'typ': 'mieter_akonto', 'vertrag_id': vertrag.id, 'name': name, **basis,
                    'kosten_anteil': round(mieter_total_kosten, 2),
                    'akonto': round(bezahltes_akonto, 2),
                    'saldo': round(saldo, 2),
                    'nachzahlung': saldo > 0,
                    'info': 'Akonto-Abrechnung', 'heiz_basis': heiz_basis,
                    'ausgeschlossen': sorted(ausgeschlossen),
                }, teile, mieter_total_kosten)

            elif nk_typ in ['pauschal', 'inbegriffen']:
                # Pauschal: Kosten fallen an, aber Differenz geht zulasten Eigentümer
                _zeile_dazu({
                    'typ': 'mieter_pauschal', 'vertrag_id': vertrag.id, 'name': name, **basis,
                    'kosten_anteil': round(mieter_total_kosten, 2),
                    'akonto': round(mieter_total_kosten, 2), # Pauschale deckt Kosten
                    'saldo': Decimal('0.00'),
                    'nachzahlung': False,
                    'info': f'Als {nk_typ.capitalize()} verrechnet', 'heiz_basis': heiz_basis,
                    'ausgeschlossen': sorted(ausgeschlossen),
                }, teile, mieter_total_kosten)

            eig_total = sum(teile_eig.values(), Decimal('0'))
            if eig_total > 0:
                if nk_typ == 'direkt':
                    info = f'Direktzahler: {name} zahlt an die Werke; Anteil beim Eigentümer'
                    grund = 'direkt'
                else:
                    info = f'Vertrag {name} schliesst aus: ' + ', '.join(sorted(teile_eig))
                    grund = 'ausgeschlossen'
                _zeile_dazu({
                    'typ': 'eigentuemer', 'name': 'Eigentümer', **basis,
                    'kosten_anteil': round(eig_total, 2), 'akonto': Decimal('0.00'),
                    'saldo': round(eig_total, 2), 'nachzahlung': True,
                    'info': info, 'grund': grund, 'bezug_vertrag_id': vertrag.id, 'bezug_name': name,
                }, teile_eig, eig_total)

        # Leerstand für Eigentümer ausweisen
        tage_leer = int(tage_periode) - tage_vermietet_total
        hgt_leer = periode_hgt - hgt_vermietet_total

        leer_teile = {}
        if hgt_leer > 0:
            for ka, b in heiz_grund.items():
                leer_teile[ka] = leer_teile.get(ka, Decimal('0')) + b * (hgt_leer / periode_hgt)
            if verbrauch_je_vertrag is not None:
                f_leer = max(Decimal('0'), (e_verbrauch - verbrauch_vermietet) / e_verbrauch)
            else:
                f_leer = hgt_leer / periode_hgt
            for ka, b in heiz_verbrauch.items():
                leer_teile[ka] = leer_teile.get(ka, Decimal('0')) + b * f_leer
        if tage_leer > 0:
            for (ka, art), b in anteil_tage.items():
                leer_teile[ka] = leer_teile.get(ka, Decimal('0')) + b * (Decimal(tage_leer) / tage_periode)
        if einheit.id in leer_person_tage and total_person_tage > 0:
            for (ka, art), b in pools.items():
                if art == 'personen':
                    leer_teile[ka] = leer_teile.get(ka, Decimal('0')) + b * leer_person_tage[einheit.id] / total_person_tage
        leer_total = sum(leer_teile.values(), Decimal('0'))

        if leer_total > Decimal('0.01'):
            _zeile_dazu({
                'typ': 'leerstand',
                'name': 'Leerstand (Eigentümer)',
                'einheit': einheit.bezeichnung, 'einheit_id': einheit.id, 'flaeche': einheit.flaeche_m2,
                'von': '-',
                'bis': '-',
                'tage': max(tage_leer, 0),
                'kosten_anteil': round(leer_total, 2),
                'akonto': Decimal('0.00'),
                'saldo': round(leer_total, 2),
                'nachzahlung': True,
                'info': 'Leerstandskosten',
            }, leer_teile, leer_total)

    # Warnung bei fehlenden Flächen: Flächenabhängige Kosten (m²-Pool inkl.
    # Honorar) werden über e_m2/total_m2 verteilt. Fehlt die Fläche einer Einheit
    # (None/0), ist ihr Anteil still 0 — die Kosten «verschwinden» bzw. landen bei
    # den anderen. Fehlt sie überall, greift der total_m2-Fallback (1) und die
    # ganze Verteilung ist unbrauchbar. In beiden Fällen: klar warnen statt still
    # eine falsche Abrechnung ausweisen (Live-Test G).
    if any(art == 'm2' and b > 0 for (ka, art), b in pools.items()):
        if _real_total_m2 <= 0:
            _warn('flaeche', "Für keine Einheit ist eine Fläche (m²) erfasst — flächenabhängige "
                             "Kosten konnten nicht verteilt werden. Bitte die Flächen der Einheiten "
                             "ergänzen, sonst ist die Abrechnung nicht korrekt.")
        else:
            _fehlend = [e.bezeichnung for e in einheiten if (e.flaeche_m2 or Decimal('0')) <= 0]
            if _fehlend:
                _warn('flaeche', "Fläche (m²) fehlt bei: " + ", ".join(_fehlend) +
                                 " — ihr Anteil an flächenabhängigen Kosten ist 0. Bitte ergänzen.")

    abrechnungen.sort(key=lambda x: x['einheit'])
    _verteile_rundungsrest(abrechnungen, round(total_kosten_gesamt, 2))
    for z in abrechnungen:
        z['aufschluesselung'] = _aufschluesselung(z.pop('_teile', {}), z['kosten_anteil'])
    # Kontrollzahl auf den ANGEZEIGTEN (gerundeten) Werten: vorher summierte sie
    # die ungerundeten Beträge und meldete «Differenz 0.00», während die
    # gedruckten Zeilen sich nicht auf das Total summierten. Ein Mieter, der
    # nachrechnet, hatte dann recht und die Abrechnung unrecht.
    kontroll_summe = sum((z['kosten_anteil'] for z in abrechnungen), Decimal('0.00'))

    # Je Kostenart: Betrag und wie verteilt wird — für Schritt «Verteilung» und den PDF-Anhang.
    kostenarten = {}
    for (ka, art), b in pools.items():
        eintrag = kostenarten.setdefault(ka, {'kostenart': ka, 'betrag': Decimal('0.00'), 'arten': []})
        eintrag['betrag'] += b
        if art not in eintrag['arten']:
            eintrag['arten'].append(art)
    for eintrag in kostenarten.values():
        eintrag['betrag'] = round(eintrag['betrag'], 2)
        s = std_schluessel.get(eintrag['kostenart'])
        eintrag['tabelle'] = s.typ if s is not None and eintrag['kostenart'] != 'heizung' else None

    return {
        'total_kosten': round(total_kosten_gesamt, 2),
        'total_flaeche': round(total_m2, 2),
        'belege_details': kategorien_liste,
        'abrechnungen': abrechnungen,
        'kontroll_summe': kontroll_summe,
        'differenz': round(total_kosten_gesamt, 2) - kontroll_summe,
        'hkvo_angewendet': hkvo_angewendet,
        'warnungen': warnungen,
        'warnung_arten': warnung_arten,
        'hinweise': hinweise,
        'kostenarten': sorted(kostenarten.values(), key=lambda x: x['kostenart']),
        'volumen_basis': m3_basis,
        'heizkosten': round(pool_heiz, 2),
        'personen_kosten': round(personen_pool, 2),
        'personen_leer_tage': personen_leer_tage,
        'leerstand_personen': modus_leer,
        'grundkosten_prozent': int(getattr(liegenschaft, 'hkvo_grundkosten_prozent', 40)),
    }

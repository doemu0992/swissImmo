"""Jahresabschluss: Erfolgskonten gegen das Jahresergebnis (2970) abschliessen.

Audit-Befund W4: Bisher existierte KEIN Abschluss-Buchungssatz — die Bilanz-View
glich mit einer nur gerechneten Eigenkapital-Zeile aus. Mechanisch stimmte das,
aber der Journal-Export ans Treuhandbüro enthielt keine Abschlussbuchungen und
das Eigentümer-Kontokorrent (2850) wurde nie gegen das Ergebnis ausgeglichen.

Gebucht wird je Erfolgskonto EINE Sammelbuchung per 31.12.:
    Ertragskonto (Soll)  an 2970   → Ertragssaldo ins Ergebnis
    2970 (Soll)          an Aufwandkonto → Aufwandsaldo ins Ergebnis
Danach sind alle Erfolgskonten für das Jahr saldiert; 2970 trägt das Ergebnis.

Idempotent über den Belegtext; `ist_abgeschlossen()` prüft den Zustand.
"""
from datetime import date
from decimal import Decimal

BELEG_PREFIX = "Jahresabschluss"


def _beleg(jahr, konto_nr):
    return f"{BELEG_PREFIX} {jahr} — Abschluss Konto {konto_nr}"


def ist_abgeschlossen(jahr, liegenschaft=None):
    """True, wenn für das Jahr bereits (überlappende) Abschlussbuchungen existieren.

    Ein Geschäftsjahr wird ENTWEDER portfolioweit ODER je Liegenschaft
    abgeschlossen. Beides zusammen würde dieselben Erfolgskonten zweimal gegen
    2970 saldieren und das Ergebnis verdoppeln.

    Audit-Befund: Vorher wurde nur auf denselben Filter geprüft. Wer zuerst
    portfolioweit abschloss (Buchungen ohne Liegenschaft) und danach mit
    gesetztem Liegenschaftsfilter erneut abschloss, fand nichts — und buchte
    alles ein zweites Mal.
    """
    from finance.models import Buchung
    # `storniert_am` mitprüfen: Eine stornierte Abschlussbuchung behält
    # ist_storno=False (das Flag trägt die Gegenbuchung). Ohne diese Bedingung
    # galt ein zurückgenommener Abschluss weiterhin als erfolgt und das
    # Geschäftsjahr liess sich nie wieder abschliessen (Audit).
    basis = Buchung.objects.filter(beleg_text__startswith=f"{BELEG_PREFIX} {jahr} —",
                                   ist_storno=False, storniert_am__isnull=True)
    # Ein portfolioweiter Abschluss deckt jede Liegenschaft mit ab.
    if basis.filter(liegenschaft__isnull=True).exists():
        return True
    if liegenschaft is None:
        # Portfolioweit: jeder bereits erfolgte Einzelabschluss blockiert.
        return basis.exists()
    return basis.filter(liegenschaft=liegenschaft).exists()


def abschluss_buchungen_q(jahr=None):
    """Q-Objekt für alle Abschlussbuchungen (optional eines Jahres) — INKLUSIVE
    ihrer Storno-Gegenbuchungen.

    Auswertungen für ein Geschäftsjahr müssen diese Buchungen ausschliessen —
    sonst saldiert sich die Erfolgsrechnung nach dem Abschluss auf null und
    Honorarbasis wie Eigentümer-Kontokorrent kippen (Audit).

    Der Storno einer Abschlussbuchung beginnt mit «Storno Beleg #…: Jahresabschluss
    …» — er beginnt also NICHT mit «Jahresabschluss» und fiel früher aus diesem
    Filter. Folge: Nach einer Abschluss-Rücknahme zählte die Erfolgsrechnung die
    stornierte Abschlussbuchung einseitig mit und verdoppelte den betroffenen
    Ertrag/Aufwand (Audit-Befund H6). Deshalb fängt das Q-Objekt beide Formen:
    das Original («… beginnt mit») und seinen Storno («… enthält : Jahresabschluss»).
    """
    from django.db.models import Q
    if jahr:
        return (Q(beleg_text__startswith=f"{BELEG_PREFIX} {jahr} —")
                | Q(beleg_text__contains=f": {BELEG_PREFIX} {jahr} —"))
    return Q(beleg_text__startswith=BELEG_PREFIX) | Q(beleg_text__contains=f": {BELEG_PREFIX} ")


def salden_erfolgskonten(jahr, liegenschaft=None):
    """Saldo je Erfolgskonto für das Geschäftsjahr (ohne bereits gebuchte
    Abschlussbuchungen). Rückgabe: Liste von (konto, saldo) — Ertrag positiv im
    Haben, Aufwand positiv im Soll."""
    from django.db.models import Sum
    from finance.models import Buchung, Buchungskonto
    von, bis = date(jahr, 1, 1), date(jahr, 12, 31)
    ergebnis = []
    for k in Buchungskonto.objects.filter(typ__in=['ertrag', 'aufwand']).order_by('nummer'):
        # Abschlussbuchungen UND ihre Storni ausschliessen — sonst zählte ein
        # erneuter Abschluss nach einer Rücknahme die Storno-Gegenbuchung als
        # echten Ertrag/Aufwand mit (H6).
        q = Buchung.objects.filter(datum__gte=von, datum__lte=bis).exclude(
            abschluss_buchungen_q(jahr))
        if liegenschaft:
            q = q.filter(liegenschaft=liegenschaft)
        soll = q.filter(soll_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        haben = q.filter(haben_konto=k).aggregate(t=Sum('betrag'))['t'] or Decimal('0.00')
        saldo = (haben - soll) if k.typ == 'ertrag' else (soll - haben)
        if saldo != 0:
            ergebnis.append((k, saldo.quantize(Decimal('0.01'))))
    return ergebnis


def buche_jahresabschluss(jahr, *, liegenschaft=None, user=None):
    """Schliesst alle Erfolgskonten des Jahres gegen 2970 ab (idempotent).
    Gibt (anzahl_buchungen, ergebnis) zurück — ergebnis > 0 = Gewinn."""
    from django.db import transaction
    from finance.booking import buche
    if ist_abgeschlossen(jahr, liegenschaft):
        return 0, Decimal('0.00')
    with transaction.atomic():
        # Innerhalb der Transaktion erneut prüfen — ein Doppelklick schickt zwei
        # Requests, die beide den Vor-Check passiert haben.
        if ist_abgeschlossen(jahr, liegenschaft):
            return 0, Decimal('0.00')
        return _buche(jahr, liegenschaft, user)


def nimm_zurueck(jahr, *, liegenschaft=None, user=None):
    """Nimmt den Jahresabschluss eines Geschäftsjahres GESAMTHAFT zurück.

    Audit-Befund H6: Eine einzelne Abschlussbuchung liess sich im Journal
    stornieren. Das verschob Vorjahresaufwand ins laufende Jahr (das Storno
    beginnt mit «Storno …», fällt also aus dem Abschluss-Ausschlussfilter) und
    liess das Jahr HALB geschlossen zurück — ein Teil der Erfolgskonten gegen
    2970 saldiert, der Rest offen. Ein Abschluss muss atomar zurückgenommen
    werden: alle Abschlussbuchungen des Jahres werden storniert und die
    Periodensperre (falls sie genau auf diesem Stichtag sass) wird gelöst.

    Gibt die Anzahl stornierter Abschlussbuchungen zurück.
    """
    from django.db import transaction
    from finance.models import Buchung
    from finance.booking import storniere_buchung
    with transaction.atomic():
        offen = Buchung.objects.filter(
            beleg_text__startswith=f"{BELEG_PREFIX} {jahr} —",
            ist_storno=False, storniert_am__isnull=True)
        if liegenschaft is not None:
            # Nur die Liegenschaft zurücknehmen, deren Abschluss zurückgenommen wird.
            # Ein portfolioweiter Abschluss (liegenschaft=None) kann nicht je LG
            # teilzurückgenommen werden — dann gibt es keine LG-spezifischen Buchungen.
            offen = offen.filter(liegenschaft=liegenschaft)
        # Die Storni werden auf den 31.12. des Abschlussjahres DATIERT (nicht ins
        # laufende Datum). Sonst läge die Rücknahme in einer anderen Periode als
        # der Abschluss: der jahresbezogene Abschluss (Erfolgskonten gegen 2970)
        # bliebe im 31.12.-Blick bestehen, während `ist_abgeschlossen` schon False
        # meldet → das Jahr wäre halb offen und ein Neuabschluss verdoppelte 2970.
        # Voraussetzung: Der Aufrufer hat eine etwaige Periodensperre auf diesem
        # Stichtag zuvor gelöst (die Buchung.save-Sperre greift sonst).
        datum = date(jahr, 12, 31)
        n = 0
        for b in list(offen):
            storniere_buchung(b, user=user, datum=datum)
            n += 1
        return n


def _buche(jahr, liegenschaft, user):
    from finance.booking import buche
    posten = salden_erfolgskonten(jahr, liegenschaft)
    datum = date(jahr, 12, 31)
    anzahl = 0
    ergebnis = Decimal('0.00')
    for k, saldo in posten:
        if saldo == 0:
            continue
        if k.typ == 'ertrag':
            # Ertragssaldo (Haben) ausbuchen: Ertragskonto an 2970
            if saldo > 0:
                buche(k, '2970', saldo, _beleg(jahr, k.nummer), datum=datum,
                      liegenschaft=liegenschaft, user=user)
            else:
                buche('2970', k, abs(saldo), _beleg(jahr, k.nummer), datum=datum,
                      liegenschaft=liegenschaft, user=user)
            ergebnis += saldo
        else:
            # Aufwandsaldo (Soll) ausbuchen: 2970 an Aufwandkonto
            if saldo > 0:
                buche('2970', k, saldo, _beleg(jahr, k.nummer), datum=datum,
                      liegenschaft=liegenschaft, user=user)
            else:
                buche(k, '2970', abs(saldo), _beleg(jahr, k.nummer), datum=datum,
                      liegenschaft=liegenschaft, user=user)
            ergebnis -= saldo
        anzahl += 1
    return anzahl, ergebnis.quantize(Decimal('0.01'))

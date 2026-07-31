"""ESTV-MWST-Abrechnung: berechnet die offiziellen Ziffern der ESTV-Abrechnung
(effektive Methode und Saldosteuersatz) und exportiert sie als CSV.

Referenz ESTV-Abrechnungsformular (Auszug relevanter Ziffern):
  200  Total vereinbarte/vereinnahmte Entgelte (Umsatz)
  289  Steuerbarer Gesamtumsatz
  300  Leistungen zum Normalsatz (Umsatz)  → 8.1 %
  310  Leistungen zum reduzierten Satz     → 2.6 %
  340  Beherbergung                        → 3.8 %
  399  Total geschuldete Steuer (Umsatzsteuer)
  400  Vorsteuer auf Material/Dienstleistungen
  405  Vorsteuer auf Investitionen/Betriebsaufwand
  479  Total Vorsteuer
  500  An die ESTV zu bezahlender Betrag (Zahllast)
  510  Guthaben der steuerpflichtigen Person
"""
import csv
import io
from decimal import Decimal, ROUND_HALF_UP

# Schweizer MWST-Normalsatz (seit 01.01.2024). Basis für die Rückrechnung des
# steuerbaren Umsatzes aus der geschuldeten Steuer (Vermietungen werden zum
# Normalsatz optiert; NK teilt den Satz der Hauptleistung).
MWST_NORMALSATZ = Decimal('8.1')


def _q(v):
    return (Decimal(v)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def berechne_estv(*, umsatz_steuerbar, umsatzsteuer, vorsteuer_material,
                  vorsteuer_invest, methode='effektiv', saldosteuersatz=Decimal('0'),
                  umsatz_brutto=None):
    """Gibt ein Dict mit den ESTV-Ziffern zurück.

    `umsatz_brutto` (Entgelt INKL. MWST) ist für die Saldosteuersatz-Methode
    massgebend: Die ESTV wendet den Saldosatz auf das Brutto-Entgelt an, nicht
    auf den Nettoumsatz (Audit-Befund K4). Fehlt der Wert, wird er aus
    Nettoumsatz + Umsatzsteuer hergeleitet.
    """
    umsatz_steuerbar = _q(umsatz_steuerbar or 0)
    if methode == 'saldo':
        satz = Decimal(saldosteuersatz or 0)
        brutto = _q(umsatz_brutto if umsatz_brutto is not None
                    else umsatz_steuerbar + _q(umsatzsteuer or 0))
        steuer = _q(brutto * satz / Decimal('100'))
        zahllast = steuer
        return {
            'methode': 'saldo', 'saldosteuersatz': satz,
            'z200': brutto, 'z289': brutto,
            'z399': steuer, 'z479': Decimal('0.00'),
            'z500': zahllast if zahllast >= 0 else Decimal('0.00'),
            'z510': Decimal('0.00'),
        }
    umsatzsteuer = _q(umsatzsteuer or 0)
    vm = _q(vorsteuer_material or 0)
    vi = _q(vorsteuer_invest or 0)
    total_vst = _q(vm + vi)
    saldo = _q(umsatzsteuer - total_vst)
    return {
        'methode': 'effektiv',
        'z200': umsatz_steuerbar, 'z289': umsatz_steuerbar,
        'z399': umsatzsteuer, 'z400': vm, 'z405': vi, 'z479': total_vst,
        'z500': saldo if saldo >= 0 else Decimal('0.00'),
        'z510': (-saldo) if saldo < 0 else Decimal('0.00'),
    }


def estv_csv(daten, *, firma, uid, periode_von, periode_bis):
    """Erzeugt eine ESTV-Abrechnungs-CSV (Ziffer;Bezeichnung;Betrag)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';')
    w.writerow(['MWST-Abrechnung', firma])
    w.writerow(['MWST-Nummer', uid or '—'])
    w.writerow(['Periode', f"{periode_von:%d.%m.%Y} – {periode_bis:%d.%m.%Y}"])
    w.writerow(['Methode', 'Saldosteuersatz' if daten['methode'] == 'saldo' else 'Effektiv'])
    if daten['methode'] == 'saldo':
        w.writerow(['Saldosteuersatz (%)', f"{daten['saldosteuersatz']}"])
    w.writerow([])
    w.writerow(['Ziffer', 'Bezeichnung', 'Betrag CHF'])
    zeilen = [
        ('200', 'Total vereinbarte Entgelte (Umsatz)', daten['z200']),
        ('289', 'Steuerbarer Gesamtumsatz', daten['z289']),
        ('399', 'Total geschuldete Steuer (Umsatzsteuer)', daten['z399']),
    ]
    if daten['methode'] == 'effektiv':
        zeilen += [
            ('400', 'Vorsteuer Material & Dienstleistungen', daten.get('z400', Decimal('0.00'))),
            ('405', 'Vorsteuer Investitionen/Betriebsaufwand', daten.get('z405', Decimal('0.00'))),
            ('479', 'Total Vorsteuer', daten['z479']),
        ]
    zeilen += [
        ('500', 'An die ESTV zu bezahlen', daten['z500']),
        ('510', 'Guthaben der steuerpflichtigen Person', daten['z510']),
    ]
    for ziffer, bez, betrag in zeilen:
        w.writerow([ziffer, bez, f"{betrag:.2f}"])
    return buf.getvalue().encode('utf-8-sig')

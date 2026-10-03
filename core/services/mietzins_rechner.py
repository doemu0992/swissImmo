"""Reine Rechenkerne der Mietzinsanpassung (OR 269a, VMWG 12a/13) — nur Decimal, keine Modelle.

Drei Faktoren, alle in Prozent des Nettomietzinses, addiert:

1. Referenzzinssatz (Art. 13 VMWG): je 0.25-Punkt-Schritt Erhöhung +3 %. Die Senkung ist
   NICHT symmetrisch, sondern der Kehrwert: n Schritte → 3n / (100 + 3n) in Prozent
   (1 Schritt −2.91 %, 2 → −5.66 %, 3 → −8.26 % …). Belegt an der Überwälzungstabelle
   von BWO/HEV; ein lineares «n × 2.91» ergibt bei 2 Schritten −5.82 % statt −5.66 %.
2. Teuerung (LIK): höchstens 40 % der LIK-Veränderung seit der Basis (Anstieg und Rückgang).
3. Allgemeine Kostensteigerung: Pauschale je Jahr (Vorgabe 0.5 %), anteilig nach Monaten.

Jeder Anteil wird einzeln auf 0.01 % gerundet, bevor addiert wird: Die auf dem amtlichen
Formular ausgewiesenen Anteile ergeben dann exakt den Gesamtwert, aus dem der Franken-
betrag folgt.
"""
from decimal import ROUND_HALF_UP, Decimal

SCHRITT = Decimal('0.25')
ERHOEHUNG_PRO_SCHRITT = Decimal('3.00')   # Art. 13 Abs. 1 lit. c VMWG (Satz < 5 %)
LIK_ANRECHENBAR = Decimal('0.40')         # Art. 269a lit. e OR / Art. 16 VMWG
KOSTEN_PAUSCHALE_JAHR = Decimal('0.5')
_HUNDERT = Decimal('100')
_ZENTEL = Decimal('0.01')


def _q(x):
    return Decimal(x).quantize(_ZENTEL, rounding=ROUND_HALF_UP)


def zins_schritte(basis_ref, aktuell_ref):
    """Anzahl Viertelprozent-Schritte (negativ = Senkung). Der Referenzzins ist amtlich auf
    0.25 gerundet; ein Wert dazwischen wird auf den nächsten Schritt gerundet (kaufm.)."""
    delta = (Decimal(str(aktuell_ref)) - Decimal(str(basis_ref))) / SCHRITT
    return int(delta.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def referenzzins_prozent(basis_ref, aktuell_ref):
    """Mietzinsänderung in % durch Referenzzinsänderung (Erhöhung +3/Schritt, Senkung 3n/(100+3n))."""
    n = zins_schritte(basis_ref, aktuell_ref)
    if n == 0:
        return Decimal('0.00')
    erhoehung = abs(n) * ERHOEHUNG_PRO_SCHRITT
    if n > 0:
        return _q(erhoehung)
    return _q(-erhoehung / (_HUNDERT + erhoehung) * _HUNDERT)


def lik_prozent(basis_lik, aktuell_lik):
    """40 % der prozentualen LIK-Veränderung seit dem Stand bei Vertragsbeginn/letzter Anpassung.
    Negativ bei sinkendem Index (Verrechnung zugunsten des Mieters)."""
    basis = Decimal(str(basis_lik))
    aktuell = Decimal(str(aktuell_lik))
    if basis <= 0:
        return Decimal('0.00')
    return _q((aktuell - basis) / basis * _HUNDERT * LIK_ANRECHENBAR)


def kostensteigerung_pauschal_pct(von, bis, satz_pro_jahr=KOSTEN_PAUSCHALE_JAHR):
    """Pauschale allgemeine Kostensteigerung zwischen zwei Daten (volle Monate, anteilig).
    `von` = «Kostensteigerung ausgeglichen bis» bzw. Vertragsbeginn. None → 0."""
    if not von or not bis or bis <= von:
        return Decimal('0.00')
    monate = (bis.year - von.year) * 12 + (bis.month - von.month)
    if bis.day < von.day:
        monate -= 1
    return _q(Decimal(max(monate, 0)) / Decimal('12') * Decimal(str(satz_pro_jahr)))


def anteil_suffix(daten, schluessel):
    """« (Anteil +3.00 %)» für die Begründungszeilen der amtlichen Formulare, sonst ''."""
    wert = (daten or {}).get(schluessel)
    if wert is None or wert == '':
        return ''
    return f" (Anteil {Decimal(str(wert)):+.2f} %)"

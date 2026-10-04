"""Exakte Verteilung eines Betrags nach Wertquoten — auf den Rappen genau.

Naives Runden (Betrag × Quote / Total, je Eigentümer gerundet) verliert oder
erfindet Rappen: 100.00 auf drei gleiche Quoten ergäbe 3 × 33.33 = 99.99. Hier
gilt die Methode des grössten Restes: Jeder bekommt den abgerundeten Anteil,
die übrigen Rappen gehen an die grössten Reste. Die Summe ist deshalb immer
exakt der Betrag.
"""
from decimal import ROUND_FLOOR, Decimal

RAPPEN = Decimal('0.01')


def verteile_nach_quoten(betrag, quoten):
    """`quoten`: {schluessel: Wertquote}. Gibt {schluessel: Anteil} zurück.

    Die Summe der Anteile ist exakt `betrag` (auf 0.01). Bei gleichem Rest
    entscheidet die Reihenfolge der Schlüssel — deterministisch.
    """
    betrag = Decimal(betrag).quantize(RAPPEN)
    quoten = {k: Decimal(v) for k, v in quoten.items()}
    total = sum(quoten.values(), Decimal('0'))
    if total <= 0:
        raise ValueError('Summe der Wertquoten muss grösser 0 sein.')
    rappen_total = int((betrag / RAPPEN).to_integral_value())
    exakt = {k: Decimal(rappen_total) * q / total for k, q in quoten.items()}
    basis = {k: int(v.to_integral_value(rounding=ROUND_FLOOR)) for k, v in exakt.items()}
    rest = rappen_total - sum(basis.values())
    nach_rest = sorted(exakt, key=lambda k: exakt[k] - basis[k], reverse=True)
    for k in nach_rest[:rest]:
        basis[k] += 1
    return {k: (Decimal(n) * RAPPEN).quantize(RAPPEN) for k, n in basis.items()}

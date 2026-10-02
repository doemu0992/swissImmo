"""Zeitwert-Rechner nach paritätischer Lebensdauertabelle.

Eine Quelle für die Berechnung. `Ausstattung.zeitwert` und
`AbnahmeMangel.berechne_mieteranteil` rufen beide diese Funktionen auf —
vorher stand die Formel zweimal da, mit `float` und `Tage / 365.25`, wodurch
sechs Jahre bei zehn Jahren Lebensdauer nicht exakt 40 % ergaben.

Regel (linear, wie in der Praxis der Schlichtungsbehörden angewendet):

    Restwertanteil = (Lebensdauer − Alter) / Lebensdauer,  begrenzt auf 0..1
    Mieteranteil   = Kosten × Restwertanteil

Das Alter zählt in vollen Kalendermonaten (nicht in Tagen): 6 Jahre sind
genau 72 Monate, bei 10 Jahren Lebensdauer also exakt 48/120 = 40 %.

Ist die Lebensdauer abgelaufen, ist der Restwert 0 und der Mieter zahlt
nichts — auch bei einem Schaden, der erst jetzt auffällt (vergilbte Wände
nach 10 Jahren bei 8 Jahren Lebensdauer). Einzige Ausnahme ist absichtliche
Beschädigung: Dort gibt es keinen Abzug «neu für alt», der Mieter trägt den
vollen Betrag.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

RAPPEN = Decimal('0.01')
_FAKTOR_STELLEN = Decimal('0.000001')

# Grundlagen des Ergebnisses — stabile Schlüssel, nie übersetzbarer Text.
KEIN_MIETERSCHADEN = 'kein_mieterschaden'   # Verursacher ist nicht der Mieter → 0
VORSATZ = 'vorsatz'                         # absichtlich beschädigt → voller Betrag
ZEITWERT = 'zeitwert'                       # Zeitwertabzug angewendet
ABGESCHRIEBEN = 'abgeschrieben'             # Lebensdauer abgelaufen → 0
OHNE_LEBENSDAUER = 'ohne_lebensdauer'       # Alter/Lebensdauer unbekannt → voller Betrag
OHNE_BETRAG = 'ohne_betrag'                 # keine Kostenbasis → 0


@dataclass(frozen=True)
class Zeitwertergebnis:
    betrag: Decimal
    faktor: Optional[Decimal]
    grundlage: str


def volle_monate(von: date, bis: date) -> int:
    """Volle Kalendermonate zwischen zwei Daten; nie negativ."""
    if bis <= von:
        return 0
    monate = (bis.year - von.year) * 12 + (bis.month - von.month)
    if bis.day < von.day:
        monate -= 1
    return max(0, monate)


def restwert_faktor(einbau_datum: Optional[date], lebensdauer_jahre: Optional[int],
                    stichtag: date) -> Optional[Decimal]:
    """Restwertanteil 0..1, oder None wenn Einbaudatum / Lebensdauer fehlen.

    None heisst «nicht erfasst», 0 heisst «gemessen: abgeschrieben» — die
    beiden dürfen nicht verwechselt werden (bekannte-fallen Nr. 15).
    """
    if not (einbau_datum and lebensdauer_jahre):
        return None
    gesamt = int(lebensdauer_jahre) * 12
    rest = max(0, gesamt - volle_monate(einbau_datum, stichtag))
    return (Decimal(rest) / Decimal(gesamt)).quantize(_FAKTOR_STELLEN, rounding=ROUND_HALF_UP)


def zeitwert(neuwert, einbau_datum, lebensdauer_jahre, stichtag) -> Optional[Decimal]:
    """Zeitwert eines Bauteils in CHF; None, wenn Daten fehlen."""
    faktor = restwert_faktor(einbau_datum, lebensdauer_jahre, stichtag)
    if neuwert is None or faktor is None:
        return None
    return (Decimal(neuwert) * faktor).quantize(RAPPEN, rounding=ROUND_HALF_UP)


def mieteranteil(kosten, faktor: Optional[Decimal], *, verursacher: str,
                 vorsaetzlich: bool = False) -> Zeitwertergebnis:
    """Vom Mieter zu tragender Betrag.

    `kosten` sind die Reparatur-/Ersatzkosten (Basis des Zeitwertabzugs),
    `faktor` kommt aus `restwert_faktor`.
    """
    null = Decimal('0.00')
    if verursacher != 'mieter':
        return Zeitwertergebnis(null, faktor, KEIN_MIETERSCHADEN)
    if kosten is None:
        return Zeitwertergebnis(null, faktor, OHNE_BETRAG)
    kosten = Decimal(kosten)
    if vorsaetzlich:
        return Zeitwertergebnis(kosten.quantize(RAPPEN, rounding=ROUND_HALF_UP), faktor, VORSATZ)
    if faktor is None:
        return Zeitwertergebnis(kosten.quantize(RAPPEN, rounding=ROUND_HALF_UP), None, OHNE_LEBENSDAUER)
    betrag = (kosten * faktor).quantize(RAPPEN, rounding=ROUND_HALF_UP)
    return Zeitwertergebnis(betrag, faktor, ABGESCHRIEBEN if faktor == 0 else ZEITWERT)

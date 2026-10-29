"""Beträge einlesen und anzeigen, an EINER Stelle (DESIGN-28).

DAS PROBLEM

Das Audit vom 28.10.2026 fand mehr als fünf eigene Parser für dieselbe Eingabe «1'450.50»: einer
ohne Apostroph (`mahnstufen._betrag`), einer ohne Komma (`mietzinsmodell._dec`), einer ohne
Leerzeichen (`stweg`), einer, der «1.450,50» zu «1.45050» machte (`bankabgleich._dec`). Jeder nahm
einen Teil der im Haus üblichen Schreibweisen, und welcher Teil, hing vom Formular ab.

DIE REGELN

* Tausender dürfen mit Apostroph (' ’ ʼ), Leerzeichen (auch geschütztem und schmalem) oder dem
  jeweils anderen Trennzeichen geschrieben werden: «1'450.50», «1 450.50», «1.450,50», «1,450.50».
* Dezimaltrenner ist der Punkt oder das Komma. Stehen beide da, ist das LETZTE der Dezimaltrenner.
* Ein einzelnes Trennzeichen ist ein Dezimaltrenner: «1,450» ist 1.450, nicht 1450 (Vorrang des
  Bestands: so rechnete `_num` immer). Mehrere gleiche («1.234.567») sind Tausender.
* «CHF», «Fr.» und «SFr.» vorn oder hinten sind erlaubt und fallen weg. Das Minuszeichen darf «−» (U+2212) sein.
* Alles andere ist kein Betrag: `betrag_parsen` wirft `ValueError`, `betrag_oder_none` gibt `None`.

Geld ist `Decimal`, nie `float`.
"""
import re
from decimal import Decimal, InvalidOperation

#: Zeichen, die nur gruppieren: Apostrophe in allen Schreibweisen, Leerzeichen in allen Breiten.
_GRUPPIERUNG = "'’ʼ‘`´    "
_ENTFERNEN = re.compile('[' + re.escape(_GRUPPIERUNG) + ']')
_WAEHRUNG = re.compile(r'^(?:s?fr\.?|chf)\s*|\s*(?:s?fr\.?|chf)$', re.IGNORECASE)
_ZAHL = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)')


def betrag_normalisieren(roh):
    """Der Text, den `Decimal()` versteht, soweit sich das ohne Raten sagen lässt.

    Prüft NICHT, ob das Ergebnis eine Zahl ist: Das tut `betrag_parsen`. Leere Eingabe bleibt leer."""
    text = str(roh if roh is not None else '').strip().replace('−', '-')
    text = _WAEHRUNG.sub('', text)
    text = _ENTFERNEN.sub('', text)
    hat_komma, hat_punkt = ',' in text, '.' in text
    if hat_komma and hat_punkt:
        if text.rfind(',') > text.rfind('.'):          # 1.450,50
            text = text.replace('.', '').replace(',', '.')
        else:                                          # 1,450.50
            text = text.replace(',', '')
    elif hat_komma:
        text = text.replace(',', '') if text.count(',') > 1 else text.replace(',', '.')
    elif text.count('.') > 1:                          # 1.234.567
        text = text.replace('.', '')
    return text


def betrag_parsen(roh):
    """Der Betrag als `Decimal`; `ValueError`, wenn die Eingabe keiner ist (auch leer)."""
    text = betrag_normalisieren(roh)
    if not _ZAHL.fullmatch(text):
        raise ValueError(f'«{roh}» ist kein Betrag')
    try:
        return Decimal(text)
    except InvalidOperation as fehler:                 # pragma: no cover - fullmatch schliesst das aus
        raise ValueError(f'«{roh}» ist kein Betrag') from fehler


def betrag_oder_none(roh):
    """Wie `betrag_parsen`, aber `None` statt Fehler."""
    try:
        return betrag_parsen(roh)
    except ValueError:
        return None


def betrag_text(wert, stellen=2):
    """«1'450.50» (Apostroph-Tausender, Punkt-Dezimal); leer bei `None` oder Unlesbarem.

    Der Wert, den das Betragsfeld beim Öffnen der Seite zeigt: exakt so liest ihn `betrag_parsen` zurück."""
    if wert is None or wert == '':
        return ''
    try:
        zahl = wert if isinstance(wert, Decimal) else betrag_parsen(wert)
    except ValueError:
        return ''
    return f'{zahl:,.{int(stellen)}f}'.replace(',', "'")

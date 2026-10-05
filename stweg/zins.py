"""Zins-Rechner (Kontokorrent) und Tilgungs-Wasserfall für die Beitragsforderungen einer Einheit.

VERZUGSZINS
  Der Satz kommt NICHT aus dem Code, sondern aus den Vorgaben der Gemeinschaft (eingetragen UND bestätigt;
  `stweg.vorgaben`). Ohne bestätigten Satz wird kein Zins gerechnet.
  Jede Beitragsforderung verzinst sich ab dem Tag NACH ihrer Fälligkeit mit dem einfachen Zins auf das jeweils
  OFFENE Kapital (Tage/365, je Zeitabschnitt auf Rappen gerundet, kaufmännisch). Wird die Forderung — auch
  teilweise — später bezahlt, läuft der Zins für die Verspätung bis zum Zahlungstag und bleibt als eigene
  Forderung (Zinsschuld) stehen, auch wenn das Kapital längst bezahlt ist. Kein Zins auf Zinsen (Art. 105 Abs. 3 OR):
  der Zins läuft nur auf Kapital, nie auf Zinsen oder Kosten.

TILGUNGSREIHENFOLGE (Wasserfall)
  Art. 85 Abs. 1 OR: Eine Teilzahlung wird, wenn der Schuldner nichts anderes bestimmt, zuerst an die KOSTEN,
  dann an die ZINSE und zuletzt an das KAPITAL angerechnet. Das ist die Reihenfolge `TILGUNGSREIHENFOLGE`. (Der
  Auftrag nannte «Art. 73 OR» — das ist der Zinsfuss — und «zuerst Zinsen, dann Spesen»; die Anrechnung regelt
  Art. 85 OR, und dort kommen die Kosten vor den Zinsen. Wer die andere Reihenfolge verlangt, ändert diese eine
  Konstante; `zuordnen` nimmt die Reihenfolge auch als Argument.)
  Die Angabe einer bezahlten Rate (Art. 86 OR, `StwegAkonto.vorschreibung`) bestimmt nur, welche KAPITAL-Forderung
  getilgt wird; Kosten und Zinsen werden davor getilgt. Das ist die für den Gläubiger vorsichtige Lesart.

  Die Anrechnung wird beim Erfassen der Zahlung berechnet und festgehalten (`StwegAkonto.an_kosten`, `an_zins`;
  der Rest ist Kapital) und so gebucht: Kosten und Kapital Haben 1110, Zins Haben 3120. Eine später rückdatiert
  erfasste Zahlung ändert die Anrechnung früherer Zahlungen NICHT (sie bleiben, wie gebucht).
"""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

NULL = Decimal('0.00')
TILGUNGSREIHENFOLGE = ('kosten', 'zins', 'kapital')            # Art. 85 Abs. 1 OR
KAPITAL_ARTEN = ('akonto', 'abrechnung', 'fonds')


def satz(liegenschaft):
    """Der bestätigte Verzugszins in Prozent pro Jahr oder None (dann wird kein Zins gerechnet)."""
    from stweg.vorgaben import vorgaben_von
    v = vorgaben_von(liegenschaft)
    if v is None or v.verzugszins_prozent is None or not v.bestaetigt_am:
        return None
    return Decimal(v.verzugszins_prozent)


def satz_unbestaetigt(liegenschaft):
    """True, wenn ein Satz eingetragen, aber noch nicht bestätigt ist (er wird dann nicht angewendet)."""
    from stweg.vorgaben import vorgaben_von
    v = vorgaben_von(liegenschaft)
    return bool(v and v.verzugszins_prozent is not None and not v.bestaetigt_am)


def _zins(kapital, prozent, tage):
    return (kapital * prozent / 100 * tage / 365).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def zins_auf_forderung(claim, stichtag, prozent):
    """Verzugszins einer Kapitalforderung bis `stichtag`: (Betrag, [Abschnitte]). Abschnitt: (von, bis, Kapital, Tage,
    Zins). `claim['anrechnungen']`: [(Datum, Betrag)] — die Kapitalzahlungen, die diese Forderung getilgt haben."""
    faellig = claim['datum']
    zahlungen = sorted(claim.get('anrechnungen', []))
    offen = claim['betrag'] - sum((b for d, b in zahlungen if d <= faellig), NULL)    # vor Fälligkeit Bezahltes
    ab, total, abschnitte = faellig, NULL, []
    for d, b in zahlungen:
        if d <= faellig:
            continue
        if d > stichtag:
            break
        tage = (d - ab).days
        if offen > 0 and tage > 0:
            z = _zins(offen, prozent, tage)
            total += z
            abschnitte.append((ab, d, offen, tage, z))
        ab, offen = d, offen - b
    tage = (stichtag - ab).days
    if offen > 0 and tage > 0:
        z = _zins(offen, prozent, tage)
        total += z
        abschnitte.append((ab, stichtag, offen, tage, z))
    return total, abschnitte


def zinsforderungen(kapital_claims, stichtag, prozent):
    """Die Zinsschuld je Kapitalforderung als eigene Forderungen (ohne Zahlung angerechnet)."""
    ergebnis = []
    for c in kapital_claims:
        total, abschnitte = zins_auf_forderung(c, stichtag, prozent)
        if total > 0:
            ergebnis.append({'datum': c['datum'], 'art': 'zins', 'betrag': total, 'schluessel': None,
                             'text': f'Verzugszins {prozent.normalize():f} % auf {c["text"]}',
                             'von': c['datum'] + timedelta(days=1), 'bis': stichtag, 'abschnitte': abschnitte,
                             'schuldner': c.get('schuldner')})
    return ergebnis


def oldest_first(claims, pool):
    """Rechnet `pool` den Forderungen an (älteste zuerst); setzt `bezahlt` und `offen`."""
    for c in sorted(claims, key=lambda c: (c['datum'], c['text'])):
        c['bezahlt'] = min(pool, c['betrag']) if pool > 0 else NULL
        pool -= c['bezahlt']
        c['offen'] = c['betrag'] - c['bezahlt']
    return claims


def zuordnen(einheit, betrag, datum, *, reihenfolge=TILGUNGSREIHENFOLGE):
    """Wie eine Zahlung von `betrag` am `datum` angerechnet wird: (an_kosten, an_zins, an_kapital), nach dem
    Wasserfall `reihenfolge`. Grundlage ist der Stand der Forderungen am Zahlungstag (ohne diese Zahlung)."""
    from stweg import inkasso
    betrag = Decimal(betrag)
    stand = inkasso.forderungen(einheit, datum)
    offen = {'kosten': sum((c['offen'] for c in stand if c['art'] in ('mahnspesen', 'betreibungskosten')), NULL),
             'zins': sum((c['offen'] for c in stand if c['art'] == 'zins'), NULL),
             'kapital': betrag}
    rest, teil = betrag, {}
    for stufe in reihenfolge:
        teil[stufe] = min(rest, offen[stufe]) if stufe != 'kapital' else rest
        rest -= teil[stufe]
    return teil['kosten'], teil['zins'], teil['kapital']

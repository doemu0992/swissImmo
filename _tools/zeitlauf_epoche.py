"""Epoch-Sekunden für den Zeitlauf der CI (SICH-45): der nächste Zeitpunkt eines Problem-Szenarios.

Der Zeitlauf (CI-Job `zeitlauf`) fährt die Suite mit einer Uhr, die auf einen kritischen Tag gestellt
ist (`_tools/uhr_schieber.c`). Die Szenarien sind relativ zu heute, damit der Lauf nicht selbst altert:

    jahreswechsel   31.12., 23:50 Uhr Zürcher Zeit (22:50 UTC): UTC- und Zürcher Tag liegen auseinander, Jahreswechsel
    neujahr         5. Januar, Mittag: Tabellen und feste Daten des Vorjahres sind überholt
    schaltag        nächster 29. Februar, Mittag
    sommernacht     1. Juli, 00:30 Uhr Zürcher Zeit (22:30 UTC am 30.06.): Monats- und Quartalsgrenze, Sommerzeit

Aufruf:  python _tools/zeitlauf_epoche.py neujahr [--ab 2026-10-29]
"""
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

ZUERICH = ZoneInfo('Europe/Zurich')


def _zeitpunkt(tag, stunde, minute):
    return datetime(tag.year, tag.month, tag.day, stunde, minute, tzinfo=ZUERICH)


def naechster(szenario, ab):
    """Der erste Zeitpunkt des Szenarios, der nach `ab` (Datum) liegt."""
    jahr = ab.year
    if szenario == 'jahreswechsel':
        kandidaten = [_zeitpunkt(date(j, 12, 31), 23, 50) for j in (jahr, jahr + 1)]
    elif szenario == 'neujahr':
        kandidaten = [_zeitpunkt(date(j, 1, 5), 12, 0) for j in (jahr, jahr + 1)]
    elif szenario == 'schaltag':
        kandidaten = [_zeitpunkt(date(j, 2, 29), 12, 0) for j in range(jahr, jahr + 9)
                      if (j % 4 == 0 and j % 100 != 0) or j % 400 == 0]
    elif szenario == 'sommernacht':
        kandidaten = [_zeitpunkt(date(j, 7, 1), 0, 30) for j in (jahr, jahr + 1)]
    else:
        raise SystemExit(f'Unbekanntes Szenario «{szenario}»')
    return next(k for k in kandidaten if k.date() > ab)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    ab = date.today()
    if '--ab' in argv:
        ab = date.fromisoformat(argv[argv.index('--ab') + 1])
    print(int(naechster(argv[1], ab).timestamp()))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
